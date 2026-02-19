#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 투자 비서 파이프라인 v2.

1. 종목 분석: 미국 S&P 500 / 한국 시총 500 → 일봉 3년, 50/100/200 이평·골드크로스·이격도
   → 1차 필터 50개 이하 → Gemini 배치 스코어링(Gap 30% + Fundamental 40% + Sentiment 30%) → 미국/한국 각 TOP 10
2. 차트 분석: 50/100/200 정배열·골든크로스·200이격도 적정·RSI 30 이하 등 → 규칙/Gemini → 미국/한국 각 TOP 10
3. 텔레그램 전송 (포맷 개선)
"""

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import (
    GEMINI_API_KEY,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    CACHE_DIR,
    OUTPUT_DIR,
)
from src.data.us_universe import fetch_sp500_tickers_with_cache
from src.data.kr_universe import fetch_kr_market_cap_top500
from src.data.market_data import fetch_ohlcv_cached
from src.logic.ohlcv_processor import process_ohlcv_to_json, add_technical_indicators
from src.logic.indicators import add_sma_50_100_200, chart_indicators, chart_score_for_filter
from src.logic.filter_candidates import filter_chart_candidates_from_dfs
from src.data.us_sources import fetch_us_stock_data, USStockData
from src.data.kr_sources import fetch_kr_stock_data
from src.intelligence.gemini_analyzer import (
    batch_stock_analysis_with_scores,
    batch_chart_analysis_top10,
)
from src.delivery.telegram_notifier import send_telegram

OHLCV_DAYS = 365 * 3
MAX_CANDIDATES = 50
BATCH_SIZE = 10
GEMINI_SLEEP_SEC = 12


def _load_ohlcv_charts(tickers: list, ticker_names: dict, cache_dir: Path, max_workers: int = 16) -> list:
    """티커 리스트에 대해 OHLCV 3년치 로드 + 기술적지표(50/100/200 포함) 적용."""
    charts = []
    for i, symbol in enumerate(tickers):
        try:
            df = fetch_ohlcv_cached(symbol, cache_dir, max_days=OHLCV_DAYS)
            df = add_technical_indicators(df)
            df = add_sma_50_100_200(df)
            ch = process_ohlcv_to_json(df, symbol, add_indicators=False)
            ch["ohlcv"] = df.to_dict(orient="index")
            ch["_df"] = df  # 규칙 필터/차트점수용
            charts.append(ch)
        except Exception:
            continue
        if (i + 1) % 100 == 0:
            print("  OHLCV 로드:", i + 1, "/", len(tickers))
    return charts


def _first_filter(charts: list, ticker_names: dict, max_cand: int = 50) -> list:
    """1차 기계 필터: 골드크로스/정배열 + 이격도 적정 → 상위 max_cand개."""
    symbol_dfs = []
    for ch in charts:
        df = ch.get("_df")
        if df is not None and len(df) >= 200:
            symbol_dfs.append((ch["symbol"], df))
    symbols = filter_chart_candidates_from_dfs(symbol_dfs, max_candidates=max_cand)
    return [ch for ch in charts if ch["symbol"] in symbols]


def _chart_top10_by_rule(charts: list, ticker_names: dict, market: str) -> list:
    """규칙 기반 차트 상위 10개: 정배열+골드크로스+이격도+RSI 30 이하 가산."""
    scored = []
    for ch in charts:
        df = ch.get("_df")
        if df is None or len(df) < 200:
            continue
        score, ok = chart_score_for_filter(df, 0.85, 1.20, 30.0)
        if not ok:
            continue
        ind = chart_indicators(df)
        scored.append((score, {
            "symbol": ch["symbol"],
            "name": ticker_names.get(ch["symbol"], ch["symbol"]),
            "reason": "정배열·골드크로스·이격도%.2f·RSI%s" % (ind.get("displacement_200") or 0, ind.get("rsi")),
            "market": market,
            **ind,
        }))
    scored.sort(key=lambda x: -x[0])
    return [x[1] for x in scored[:10]]


def run():
    print("=" * 60)
    print("  AI 투자 비서 파이프라인 v2")
    print("=" * 60)

    # --- 1. 유니버스 ---
    print("\n[1/6] 유니버스: 미국 S&P 500, 한국 시총 500")
    us_tickers = fetch_sp500_tickers_with_cache(CACHE_DIR)
    us_tickers = us_tickers[:500]
    kr_tickers, kr_names = fetch_kr_market_cap_top500(CACHE_DIR)
    kr_tickers = kr_tickers[:500]
    us_names = {t: t for t in us_tickers}
    print("  미국:", len(us_tickers), "종목 / 한국:", len(kr_tickers), "종목")

    # --- 2. OHLCV 3년 + 50/100/200 이평·RSI ---
    print("\n[2/6] OHLCV 3년 + 50/100/200 이평·골드크로스·이격도 계산")
    us_charts = _load_ohlcv_charts(us_tickers, us_names, CACHE_DIR)
    kr_charts = _load_ohlcv_charts(kr_tickers, kr_names, CACHE_DIR)
    print("  미국 차트:", len(us_charts), "개 / 한국 차트:", len(kr_charts), "개")

    # --- 3. 1차 필터 (50개 이하) ---
    print("\n[3/6] 1차 필터: 골드크로스·정배열·이격도 → 후보 50개 이하")
    us_candidates = _first_filter(us_charts, us_names, MAX_CANDIDATES)
    kr_candidates = _first_filter(kr_charts, kr_names, MAX_CANDIDATES)
    print("  미국 후보:", len(us_candidates), "개 / 한국 후보:", len(kr_candidates), "개")

    # --- 4. 종목 분석: 전문가/재무 데이터 수집 후 Gemini 배치 스코어링 ---
    print("\n[4/6] 종목 분석: Seeking Alpha·Finviz·Yahoo / Fnguide → Gemini 배치 TOP 10")
    us_stock_data_list = []
    for ch in us_candidates[:MAX_CANDIDATES]:
        try:
            d = fetch_us_stock_data(ch["symbol"])
            d.current_price = d.current_price or (chart_indicators(ch["_df"]).get("close"))
            us_stock_data_list.append({
                "ticker": d.ticker,
                "name": us_names.get(d.ticker, d.ticker),
                "current_price": d.current_price,
                "target_price": d.target_price,
                "opm_pct": d.opm_pct,
                "seeking_alpha_headlines": d.seeking_alpha_headlines,
                "finviz_targets": d.finviz_targets,
            })
            time.sleep(0.5)
        except Exception:
            continue

    kr_stock_data_list = []
    for ch in kr_candidates[:MAX_CANDIDATES]:
        try:
            close = chart_indicators(ch["_df"]).get("close") if ch.get("_df") is not None else 0
            d = fetch_kr_stock_data(ch["symbol"], current_price=close)
            kr_stock_data_list.append({
                "ticker": d.ticker,
                "name": kr_names.get(d.ticker, d.ticker),
                "current_price": d.current_price or close,
                "target_price": d.target_price,
                "opm_pct": d.opm_pct,
                "headlines": d.headlines_or_reports,
            })
            time.sleep(0.5)
        except Exception:
            continue

    stock_top10_us = []
    stock_top10_kr = []
    if GEMINI_API_KEY:
        stock_top10_us, _ = batch_stock_analysis_with_scores(
            us_stock_data_list[:50], GEMINI_API_KEY, BATCH_SIZE, GEMINI_SLEEP_SEC, "US"
        )
        time.sleep(GEMINI_SLEEP_SEC)
        stock_top10_kr, _ = batch_stock_analysis_with_scores(
            kr_stock_data_list[:50], GEMINI_API_KEY, BATCH_SIZE, GEMINI_SLEEP_SEC, "KR"
        )
    if not stock_top10_us and us_stock_data_list:
        for s in us_stock_data_list[:10]:
            stock_top10_us.append({"ticker": s["ticker"], "name": s["name"], "score": 50, "reason": "API 미사용", "market": "US"})
    if not stock_top10_kr and kr_stock_data_list:
        for s in kr_stock_data_list[:10]:
            stock_top10_kr.append({"ticker": s["ticker"], "name": s["name"], "score": 50, "reason": "API 미사용", "market": "KR"})

    # --- 5. 차트 분석: 정배열·골드크로스·이격도·RSI → 규칙/Gemini TOP 10 ---
    print("\n[5/6] 차트 분석: 50/100/200 정배열·골드크로스·이격도·RSI 30 이하 → TOP 10")
    chart_summary_us = []
    for ch in us_candidates:
        df = ch.get("_df")
        if df is None or len(df) < 200:
            continue
        ind = chart_indicators(df)
        chart_summary_us.append({
            "symbol": ch["symbol"],
            "name": us_names.get(ch["symbol"], ch["symbol"]),
            **ind,
        })
    chart_summary_kr = []
    for ch in kr_candidates:
        df = ch.get("_df")
        if df is None or len(df) < 200:
            continue
        ind = chart_indicators(df)
        chart_summary_kr.append({
            "symbol": ch["symbol"],
            "name": kr_names.get(ch["symbol"], ch["symbol"]),
            **ind,
        })

    chart_top10_us = []
    chart_top10_kr = []
    if GEMINI_API_KEY and chart_summary_us:
        chart_top10_us, _ = batch_chart_analysis_top10(
            chart_summary_us[:50], GEMINI_API_KEY, BATCH_SIZE, GEMINI_SLEEP_SEC, "US"
        )
    if GEMINI_API_KEY and chart_summary_kr:
        chart_top10_kr, _ = batch_chart_analysis_top10(
            chart_summary_kr[:50], GEMINI_API_KEY, BATCH_SIZE, GEMINI_SLEEP_SEC, "KR"
        )
    if not chart_top10_us:
        chart_top10_us = _chart_top10_by_rule(us_candidates, us_names, "US")
    if not chart_top10_kr:
        chart_top10_kr = _chart_top10_by_rule(kr_candidates, kr_names, "KR")

    # --- 6. 텔레그램 포맷 (아이콘·섹션) ---
    print("\n[6/6] 텔레그램 전송")
    def esc(t):
        t = (t or "").replace("```", "").replace("&", "＆").replace("<", "＜").replace(">", "＞")
        return t[:250]

    parts = [
        "📊 <b>AI 투자 비서 리포트</b>",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "📌 <b>1. 종목 분석</b> (Gap 30% + Fundamental 40% + Sentiment 30%)",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        "🇰🇷 <b>한국 TOP 10</b>",
    ]
    for i, r in enumerate(stock_top10_kr[:10], 1):
        parts.append("%d. %s (%s) | Score %s\n   %s" % (i, esc(r.get("name")), r.get("ticker"), r.get("score"), esc(r.get("reason"))))
    parts.append("")
    parts.append("🇺🇸 <b>미국 TOP 10</b>")
    for i, r in enumerate(stock_top10_us[:10], 1):
        parts.append("%d. %s (%s) | Score %s\n   %s" % (i, esc(r.get("name")), r.get("ticker"), r.get("score"), esc(r.get("reason"))))
    parts.extend([
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "📈 <b>2. 차트 분석</b> (50/100/200 정배열·골드크로스·이격도·RSI)",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        "🇰🇷 <b>한국 TOP 10</b>",
    ])
    for i, r in enumerate(chart_top10_kr[:10], 1):
        parts.append("%d. %s (%s)\n   %s" % (i, esc(r.get("name")), r.get("symbol"), esc(r.get("reason"))))
    parts.append("")
    parts.append("🇺🇸 <b>미국 TOP 10</b>")
    for i, r in enumerate(chart_top10_us[:10], 1):
        parts.append("%d. %s (%s)\n   %s" % (i, esc(r.get("name")), r.get("symbol"), esc(r.get("reason"))))

    message = "\n".join(parts)
    chunk = 4000
    if len(message) > chunk:
        for i in range(0, len(message), chunk):
            send_telegram(message[i : i + chunk], TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
            time.sleep(1)
    else:
        send_telegram(message, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)

    # 저장
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "stock_analysis_kr": stock_top10_kr,
        "stock_analysis_us": stock_top10_us,
        "chart_analysis_kr": chart_top10_kr,
        "chart_analysis_us": chart_top10_us,
    }
    with open(OUTPUT_DIR / "daily_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("  저장:", OUTPUT_DIR / "daily_report.json")
    print("  완료.")


if __name__ == "__main__":
    run()
