#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 투자 비서 메인 파이프라인.

실행 순서:
1. Data: 국장(KOSPI+KOSDAQ) 종목 + OHLCV (일봉 3년) + 애널리스트 정보
2. Logic: OHLCV JSON + 기술적 지표 + 압축
3. Intelligence: 정답 차트 샘플 기반 Gemini 1회 호출 패턴 매칭
4. Delivery: 텔레그램 (차트 분석 / 종목 분석)
"""

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import (
    GEMINI_API_KEY,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    SAMPLE_DIR,
    OUTPUT_DIR,
    CACHE_DIR,
    DART_API_KEY,
)
from src.data.kr_universe import fetch_kr_tickers_with_cache
from src.data.market_data import fetch_ohlcv_cached
from src.data.analyst_sources import fetch_all_analyst_items
from src.logic.ohlcv_processor import process_ohlcv_to_json
from src.logic.chart_compress import compress_all_charts
from src.data.rss_sources import fetch_all_rss_items
from src.intelligence.gemini_analyzer import (
    load_sample_charts,
    analyze_all_charts_single_call,
    get_hottest_analyst_analyses,
)
from src.delivery.telegram_notifier import send_telegram


def run():
    """전체 파이프라인 실행."""
    print("=" * 50)
    print("AI 투자 비서 파이프라인 시작")
    print("=" * 50)

    # 1. Data: 국장(KOSPI+KOSDAQ) 전체 종목 (제한 없음)
    print("\n[1/5] Data Layer: 국장(KOSPI+KOSDAQ) 종목 수집...")
    tickers, ticker_names = fetch_kr_tickers_with_cache(CACHE_DIR)
    print("  분석 대상:", len(tickers), "종목")

    # 2. Logic: OHLCV 캐시(3년) + 증분 갱신 + 기술적 지표 (병렬 처리, financials 스킵)
    print("\n[2/5] Logic Layer: OHLCV 캐시 갱신 + 기술적 지표 처리 (병렬)...")
    charts = []
    max_workers = 24

    def _fetch_and_process(symbol: str):
        try:
            df = fetch_ohlcv_cached(symbol, CACHE_DIR, max_days=365 * 3)
            chart_json = process_ohlcv_to_json(df, symbol, add_indicators=True)
            chart_json["financials_summary"] = {}  # 1회 호출 모드에서는 미사용
            return chart_json
        except Exception as e:
            return None

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_fetch_and_process, sym): sym for sym in tickers}
        done = 0
        for f in as_completed(futures):
            done += 1
            if done % 300 == 0:
                print(f"  진행: {done}/{len(tickers)}")
            result = f.result()
            if result:
                charts.append(result)

    print(f"  처리 완료: {len(charts)}개 종목")

    # 2b. 애널리스트 정보 수집 (Founders Fund, DART, 키움, RSS/Gemini 필터)
    print("\n[2b/5] 애널리스트 소스 수집...")
    analyst_recommended, analyst_warning = fetch_all_analyst_items(
        api_key=GEMINI_API_KEY,
        dart_api_key=DART_API_KEY,
    )

    # 2a. 최근 핫한 애널리스트 분석 Top 10 (미국·한국)
    top10_hot: list = []
    rss_items = fetch_all_rss_items()
    rss_texts = [f"[{r.source}] {r.title} | {r.summary[:150]}" for r in rss_items]
    if GEMINI_API_KEY and rss_texts:
        top10_hot = get_hottest_analyst_analyses(rss_texts, GEMINI_API_KEY)
    # fallback: 핫한 Top 10 실패 시 추천+위험신호에서 10건 채우기
    if not top10_hot:
        combined = [
            {"ticker": a.ticker, "name": a.name, "analysis": a.reason, "source": a.source}
            for a in (analyst_recommended + analyst_warning)[:10]
        ]
        top10_hot = combined
    print("  추천:", len(analyst_recommended), "건 / 위험신호:", len(analyst_warning), "건")

    # 3. Intelligence: 1회 호출로 전체 차트 분석
    print("\n[3/5] Intelligence Layer: Gemini 1회 호출 패턴 매칭...")
    samples = load_sample_charts(SAMPLE_DIR)
    print("  정답 샘플:", len(samples), "개")

    compressed = compress_all_charts(charts, ticker_names)
    api_error_msg: str | None = None
    pattern_matches: list = []

    if GEMINI_API_KEY:
        pattern_matches, api_error_msg = analyze_all_charts_single_call(
            compressed, samples, GEMINI_API_KEY
        )
        if api_error_msg:
            print("  [오류] %s" % api_error_msg)
        print("  차트 패턴 적합:", len(pattern_matches), "종목")
    else:
        print("  경고: GEMINI_API_KEY 없음. 분석 스킵.")

    # 4. Delivery: 텔레그램 (차트 분석 / 종목 분석)
    print("\n[4/5] Delivery Layer: 텔레그램 전송...")

    def _esc(t):
        t = (t or "").replace("```", "").replace("{", "").replace("}", "")
        return t.replace("&", "＆").replace("<", "＜").replace(">", "＞")

    msg_parts = ["📊 <b>AI 투자 비서 일일 리포트</b>\n"]

    # -- 차트 분석 -- (Gemini 초과 시 여기에만 에러 표시)
    msg_parts.append("<b>-- 차트 분석 --</b>\n")
    if api_error_msg:
        msg_parts.append("⚠️ %s\n" % _esc(api_error_msg[:400]))
    elif pattern_matches:
        for i, m in enumerate(pattern_matches[:20], 1):
            name = m.get("name", m.get("symbol", "?"))
            ticker = m.get("symbol", "?")
            reason = _esc(m.get("chart_reason", m.get("reason", ""))[:200])
            msg_parts.append("%d. %s, %s, %s\n" % (i, name, ticker, reason))
    else:
        msg_parts.append("적합 종목 없음\n")
    msg_parts.append("\n")

    # -- 종목 분석 (애널리스트/펀드) --
    msg_parts.append("<b>-- 종목 분석 --</b>\n")
    msg_parts.append("📌 추천 (매수·상향 등)\n")
    if analyst_recommended:
        for i, a in enumerate(analyst_recommended[:15], 1):
            msg_parts.append(
                "%d. %s, %s, %s, 출처: %s\n"
                % (i, a.name, a.ticker, _esc(a.reason)[:150], a.source)
            )
    else:
        msg_parts.append("없음\n")
    msg_parts.append("\n⚠️ 위험신호 (매도·하향 등)\n")
    if analyst_warning:
        for i, a in enumerate(analyst_warning[:15], 1):
            msg_parts.append(
                "%d. %s, %s, %s, 출처: %s\n"
                % (i, a.name, a.ticker, _esc(a.reason)[:150], a.source)
            )
    else:
        msg_parts.append("없음\n")

    # -- 최근 핫한 애널리스트 분석 Top 10 (미국·한국) --
    msg_parts.append("\n<b>-- 최근 핫한 애널리스트 분석 Top 10 --</b>\n")
    if top10_hot:
        for i, a in enumerate(top10_hot[:10], 1):
            src = a.get("source", "")
            msg_parts.append(
                "%d. %s (%s): %s  출처:%s\n"
                % (i, a.get("name", "?"), a.get("ticker", "?"), _esc(a.get("analysis", ""))[:150], src)
            )
    else:
        msg_parts.append("분석 없음\n")

    message = "\n".join(msg_parts)
    chunk_size = 4000
    if len(message) > chunk_size:
        chunks = [message[i : i + chunk_size] for i in range(0, len(message), chunk_size)]
        sent = all(send_telegram(chunk, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID) for chunk in chunks)
    else:
        sent = send_telegram(message, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    print("  텔레그램 전송:", "성공" if sent else "실패")

    # 5. 결과 저장
    print("\n[5/5] 결과 저장...")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "tickers": tickers,
        "pattern_matches": pattern_matches,
        "analyst_recommended": [
            {"name": a.name, "ticker": a.ticker, "reason": a.reason, "source": a.source}
            for a in analyst_recommended
        ],
        "analyst_warning": [
            {"name": a.name, "ticker": a.ticker, "reason": a.reason, "source": a.source}
            for a in analyst_warning
        ],
        "top10_hot_analyst": top10_hot,
        "api_error": api_error_msg,
    }
    with open(OUTPUT_DIR / "daily_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("  저장:", OUTPUT_DIR / "daily_report.json")


if __name__ == "__main__":
    run()
