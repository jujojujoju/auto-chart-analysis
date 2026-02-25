#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 투자 비서 파이프라인 v2.

1. 종목 분석: 미국 S&P 500 / 한국 시총 500 → 일봉 3년, 50/100/200 이평·골드크로스·이격도
   → 1차 필터 50개 이하 → Gemini 배치 스코어링(Gap 30% + Fundamental 40% + Sentiment 30%) → 미국/한국 각 TOP 10
2. 차트 분석: 50/100/200 정배열·골든크로스·200이격도 적정·RSI 30 이하 등 → 규칙/Gemini → 미국/한국 각 TOP 10
3. 텔레그램 전송 (포맷 개선)
"""

import json
import logging
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

# 라이브러리(yfinance, pandas 등) deprecation/경고 억제
warnings.filterwarnings("ignore")

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
# 종목별 종목분석 캐시: 이 기간(일) 이내면 캐시 사용, 넘으면 재수집
STOCK_ANALYSIS_CACHE_TTL_DAYS = 3

# 파이프라인 전용 로거 (파일 + 터미널). run() 시작 시 _setup_pipeline_logger()로 초기화.
PIPELINE_LOGGER = "pipeline"


def _setup_pipeline_logger() -> Path:
    """로그를 파일(OUTPUT_DIR/pipeline_YYYYMMDD_HHMMSS.log)과 터미널에 동시에 남김."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = OUTPUT_DIR / f"pipeline_{ts}.log"
    log = logging.getLogger(PIPELINE_LOGGER)
    log.setLevel(logging.DEBUG)
    log.propagate = False
    log.handlers.clear()
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    fh.setFormatter(fmt)
    ch.setFormatter(fmt)
    log.addHandler(fh)
    log.addHandler(ch)
    log.info("로그 파일: %s", log_path)
    return log_path


def _stock_analysis_cache_path(cache_dir: Path, market: str, ticker: str) -> Path:
    """종목별 종목분석 캐시 파일 경로. market='us'|'kr', ticker는 파일명에 쓰기 위해 . → _ 치환."""
    safe = ticker.replace(".", "_")
    return (cache_dir / "stock_analysis_us" if market == "us" else cache_dir / "stock_analysis_kr") / f"{safe}.json"


def _load_stock_analysis_cached(cache_path: Path, ttl_days: float) -> Optional[dict]:
    """캐시 파일에서 종목분석 로드. fetched_at 기준 ttl_days 이내면 반환, 아니면 None."""
    if not cache_path.exists():
        return None
    try:
        with open(cache_path, encoding="utf-8") as f:
            obj = json.load(f)
        fetched_at = obj.get("fetched_at")
        data = obj.get("data")
        if not fetched_at or not isinstance(data, dict):
            return None
        t = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
        if t.tzinfo is not None:
            t = t.replace(tzinfo=None)
        if datetime.now() - t > timedelta(days=ttl_days):
            return None
        return data
    except (json.JSONDecodeError, OSError, ValueError):
        return None


def _save_stock_analysis_cached(cache_path: Path, data: dict) -> None:
    """종목분석 결과를 캐시에 저장."""
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        obj = {"fetched_at": datetime.now().isoformat(), "data": data}
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def _load_one(symbol: str, cache_dir: Path) -> Optional[dict]:
    """단일 종목 OHLCV 로드 + 지표. 실패 시 None."""
    try:
        df = fetch_ohlcv_cached(symbol, cache_dir, max_days=OHLCV_DAYS)
        df = add_technical_indicators(df)
        df = add_sma_50_100_200(df)
        ch = process_ohlcv_to_json(df, symbol, add_indicators=False)
        ch["ohlcv"] = df.to_dict(orient="index")
        ch["_df"] = df
        return ch
    except Exception:
        return None


def _load_ohlcv_charts(tickers: list, ticker_names: dict, cache_dir: Path, max_workers: int = 16) -> list:
    """티커 리스트에 대해 OHLCV 3년치 로드 + 기술적지표(50/100/200 포함) 적용. 병렬 처리."""
    charts = []
    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_load_one, sym, cache_dir): sym for sym in tickers}
        for f in as_completed(futures):
            done += 1
            if done % 200 == 0:
                logging.getLogger(PIPELINE_LOGGER).debug("  OHLCV 로드: %d / %d", done, len(tickers))
            r = f.result()
            if r is not None:
                charts.append(r)
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
    log_path = _setup_pipeline_logger()
    log = logging.getLogger(PIPELINE_LOGGER)
    log.info("=" * 60)
    log.info("  AI 투자 비서 파이프라인 v2")
    log.info("=" * 60)

    # --- 1. 유니버스 (최초 500 선별은 캐시 미사용, 항상 재수집) ---
    log.info("[1/6] 유니버스: 미국 S&P 500, 한국 시총 500")
    us_tickers = fetch_sp500_tickers_with_cache(CACHE_DIR)
    us_tickers = us_tickers[:500]
    log.info("  미국: Wikipedia S&P 500 재수집(캐시 없음) → 티커 %d개", len(us_tickers))
    if us_tickers:
        log.debug("  미국 티커 샘플: %s ... %s", ", ".join(us_tickers[:5]), ", ".join(us_tickers[-3:]))
    kr_tickers, kr_names = fetch_kr_market_cap_top500(CACHE_DIR)
    kr_tickers = kr_tickers[:500]
    log.info("  한국: FinanceDataReader KRX 시총순 재수집(캐시 없음) → 티커 %d개, 종목명 %d개", len(kr_tickers), len(kr_names))
    if kr_tickers:
        log.debug("  한국 티커 샘플: %s ... %s", ", ".join(kr_tickers[:3]), ", ".join(kr_tickers[-2:]))
    us_names = {t: t for t in us_tickers}
    log.info("  결과: 미국 %d종목 / 한국 %d종목", len(us_tickers), len(kr_tickers))

    # --- 2. OHLCV 3년 + 50/100/200 이평·RSI ---
    log.info("[2/6] OHLCV 3년 + 50/100/200 이평·골드크로스·이격도 계산")
    log.info("  데이터 소스: yfinance + 캐시 %s/ohlcv/*.csv (일봉, 최대 %d일)", CACHE_DIR, OHLCV_DAYS)
    us_charts = _load_ohlcv_charts(us_tickers, us_names, CACHE_DIR)
    kr_charts = _load_ohlcv_charts(kr_tickers, kr_names, CACHE_DIR)
    log.info("  미국: 요청 %d종목 → 성공 %d개 차트 (50/100/200 이평·RSI 적용) / 한국: 요청 %d종목 → 성공 %d개", len(us_tickers), len(us_charts), len(kr_tickers), len(kr_charts))
    if us_charts:
        log.debug("  미국 차트 샘플 심볼: %s", [c["symbol"] for c in us_charts[:5]])
    if kr_charts:
        log.debug("  한국 차트 샘플 심볼: %s", [c["symbol"] for c in kr_charts[:5]])

    # --- 3. 1차 필터 (50개 이하) ---
    log.info("[3/6] 1차 필터: 골드크로스·정배열·이격도 적정 → 후보 %d개 이하", MAX_CANDIDATES)
    log.info("  필터 기준: filter_chart_candidates (골든크로스/정배열 + 이격도 0.85~1.20 + 거래량 등)")
    us_candidates = _first_filter(us_charts, us_names, MAX_CANDIDATES)
    kr_candidates = _first_filter(kr_charts, kr_names, MAX_CANDIDATES)
    log.info("  미국: 입력 %d개 차트 → 필터 통과 %d개 후보 / 한국: 입력 %d개 → 통과 %d개", len(us_charts), len(us_candidates), len(kr_charts), len(kr_candidates))
    if us_candidates:
        log.debug("  미국 후보 심볼 (%d개 전체): %s", len(us_candidates), [c["symbol"] for c in us_candidates])
    if kr_candidates:
        log.debug("  한국 후보 심볼 (%d개 전체): %s", len(kr_candidates), [c["symbol"] for c in kr_candidates])

    # --- 4. 종목 분석: 전문가/재무 데이터 수집(종목별 캐시 3일 TTL) 후 Gemini 배치 스코어링 ---
    log.info("[4/6] 종목 분석: 미국 Finviz·Yahoo / 한국 Fnguide → Gemini 배치 TOP 10")
    log.info("  종목별 캐시: %s (TTL %d일, 만료 시에만 재수집)", CACHE_DIR / "stock_analysis_us|kr", STOCK_ANALYSIS_CACHE_TTL_DAYS)
    log.info("  퀀트 점수 공식: 기본40 + 괴리(20%%↑+25, 10%%↑+15) + OPM(10%%↑+25, 0%%↑+10) + PER(<10 +12, <15 +8, <25 +4, >80 -5) + PBR(<1 +8, <2 +4) + ROE(≥20%% +10, ≥15 +6, ≥10 +3) → 상한98")
    us_stock_data_list: list[dict[str, Any]] = []
    us_cache_hits = 0
    for ch in us_candidates[:MAX_CANDIDATES]:
        try:
            ticker = ch["symbol"]
            cache_path = _stock_analysis_cache_path(CACHE_DIR, "us", ticker)
            cached = _load_stock_analysis_cached(cache_path, STOCK_ANALYSIS_CACHE_TTL_DAYS)
            if cached is not None:
                cached.setdefault("finviz_targets", [])
                cached.setdefault("headlines", [])
                us_stock_data_list.append(cached)
                us_cache_hits += 1
                fv_url = cached.get("finviz_url") or f"https://finviz.com/quote.ashx?t={ticker}"
                log.debug("  미국 %s [캐시 사용] Finviz %s → current=%s target=%s OPM=%s", ticker, fv_url, cached.get("current_price"), cached.get("target_price"), cached.get("opm_pct"))
                continue
            d = fetch_us_stock_data(ticker)
            d.current_price = d.current_price or (chart_indicators(ch["_df"]).get("close"))
            row = {
                "ticker": d.ticker,
                "name": us_names.get(d.ticker, d.ticker),
                "current_price": d.current_price,
                "target_price": d.target_price,
                "opm_pct": d.opm_pct,
                "finviz_targets": d.finviz_targets,
                "headlines": [],
                "finviz_url": getattr(d, "finviz_url", None),
                "per": getattr(d, "per", None),
                "pbr": getattr(d, "pbr", None),
                "roe_pct": getattr(d, "roe_pct", None),
                "eps": getattr(d, "eps", None),
                "div_yield_pct": getattr(d, "div_yield_pct", None),
            }
            us_stock_data_list.append(row)
            _cache_keys_us = ("ticker", "name", "current_price", "target_price", "opm_pct", "headlines", "finviz_url", "per", "pbr", "roe_pct", "eps", "div_yield_pct")
            _save_stock_analysis_cached(cache_path, {k: v for k, v in row.items() if k in _cache_keys_us})
            fv_url = getattr(d, "finviz_url", None) or f"https://finviz.com/quote.ashx?t={ticker}"
            recom = next((r.get("value") for r in (d.finviz_targets or []) if "ecom" in r.get("key", "").lower() or "rec" in r.get("key", "").lower()), None)
            n_rows = len(d.finviz_targets or [])
            # Recom=Finviz 추천등급(Recommendation), 테이블 0행=해당 종목 페이지에서 목표가/추천 테이블 파싱된 행 수(0이면 없거나 파싱 실패)
            log.debug("  미국 %s [신규 수집] Finviz 목표가=%s Recom(추천등급)=%s 파싱행=%d | Yahoo 현재가·OPM·PER·PBR·ROE", ticker, d.target_price, recom or "없음", n_rows)
            time.sleep(0.5)
        except Exception as ex:
            log.debug("  미국 요청 %s → 예외: %s", ch.get("symbol", "?"), ex)
            continue
    n_us_price = sum(1 for s in us_stock_data_list if s.get("current_price"))
    n_us_target = sum(1 for s in us_stock_data_list if s.get("target_price"))
    n_us_opm = sum(1 for s in us_stock_data_list if s.get("opm_pct") is not None)
    n_us_per = sum(1 for s in us_stock_data_list if s.get("per") is not None)
    n_us_pbr = sum(1 for s in us_stock_data_list if s.get("pbr") is not None)
    n_us_roe = sum(1 for s in us_stock_data_list if s.get("roe_pct") is not None)
    log.info("  미국 데이터 소스: Finviz(목표가·Recom), Yahoo(현재가·OPM·PER·PBR·ROE)")
    log.info("  미국 수집 결과: 총 %d종목 | 현재가 %d 목표가 %d OPM %d PER %d PBR %d ROE %d | 캐시 %d 신규 %d", len(us_stock_data_list), n_us_price, n_us_target, n_us_opm, n_us_per, n_us_pbr, n_us_roe, us_cache_hits, len(us_stock_data_list) - us_cache_hits)
    if us_stock_data_list:
        s0 = us_stock_data_list[0]
        log.debug("  미국 수집 샘플(첫 종목): %s | 현재가=%s 목표가=%s OPM=%s PER=%s PBR=%s ROE=%s", s0.get("ticker"), s0.get("current_price"), s0.get("target_price"), s0.get("opm_pct"), s0.get("per"), s0.get("pbr"), s0.get("roe_pct"))

    kr_stock_data_list = []
    kr_cache_hits = 0
    for ch in kr_candidates[:MAX_CANDIDATES]:
        try:
            ticker = ch["symbol"]
            close = chart_indicators(ch["_df"]).get("close") if ch.get("_df") is not None else 0
            cache_path = _stock_analysis_cache_path(CACHE_DIR, "kr", ticker)
            cached = _load_stock_analysis_cached(cache_path, STOCK_ANALYSIS_CACHE_TTL_DAYS)
            if cached is not None:
                cached["current_price"] = cached.get("current_price") or close
                kr_stock_data_list.append(cached)
                kr_cache_hits += 1
                fg_url = cached.get("fnguide_url") or f"https://comp.fnguide.com/SVO2/ASP/SVD_Main.asp?gicode=A{(ticker or '').split('.')[0].zfill(6)}"
                log.debug("  한국 %s [캐시 사용] %s → current=%s target=%s OPM=%s 리포트=%d개", ticker, fg_url, cached.get("current_price"), cached.get("target_price"), cached.get("opm_pct"), len(cached.get("headlines") or []))
                for j, r in enumerate((cached.get("headlines") or [])[:5]):
                    log.debug("    리포트 %d: %s", j + 1, (r or "")[:80])
                continue
            d = fetch_kr_stock_data(ticker, current_price=close)
            hr = getattr(d, "headlines_or_reports", None)
            hr_list = hr if isinstance(hr, (list, tuple)) else []
            row = {
                "ticker": d.ticker,
                "name": kr_names.get(d.ticker, d.ticker),
                "current_price": d.current_price or close,
                "target_price": d.target_price,
                "opm_pct": d.opm_pct,
                "headlines": hr_list,
                "fnguide_url": getattr(d, "fnguide_url", None),
                "per": getattr(d, "per", None),
                "pbr": getattr(d, "pbr", None),
                "roe_pct": getattr(d, "roe_pct", None),
                "eps": getattr(d, "eps", None),
                "debt_ratio_pct": getattr(d, "debt_ratio_pct", None),
                "div_yield_pct": getattr(d, "div_yield_pct", None),
                "actual_op_income_100m": getattr(d, "actual_op_income_100m", None),
                "expected_op_yoy_pct": getattr(d, "expected_op_yoy_pct", None),
                "yoy_pct": getattr(d, "yoy_pct", None),
                "market_cap_100m": getattr(d, "market_cap_100m", None),
                "foreign_pct": getattr(d, "foreign_pct", None),
                "beta": getattr(d, "beta", None),
                "return_1m_pct": getattr(d, "return_1m_pct", None),
                "return_3m_pct": getattr(d, "return_3m_pct", None),
                "return_1y_pct": getattr(d, "return_1y_pct", None),
                "business_summary": getattr(d, "business_summary", None),
                "consensus_line": getattr(d, "consensus_line", None),
                "institutional_holdings": getattr(d, "institutional_holdings", None) or [],
            }
            kr_stock_data_list.append(row)
            _save_stock_analysis_cached(cache_path, row)
            fg_url = getattr(d, "fnguide_url", None) or f"https://comp.fnguide.com/SVO2/ASP/SVD_Main.asp?gicode=A{(ticker or '').split('.')[0].zfill(6)}"
            log.debug("  한국 %s [신규 수집] Fnguide %s → 리포트 %d개", ticker, fg_url, len(hr_list))
            if hr_list:
                for j, r in enumerate(hr_list[:5]):
                    log.debug("    리포트 %d: %s", j + 1, (r or "")[:80])
            else:
                log.debug("    리포트 없음")
            time.sleep(0.5)
        except Exception as ex:
            log.debug("  한국 요청 %s → 예외: %s", ch.get("symbol", "?"), ex)
            continue
    n_kr_price = sum(1 for s in kr_stock_data_list if s.get("current_price"))
    n_kr_target = sum(1 for s in kr_stock_data_list if s.get("target_price"))
    n_kr_opm = sum(1 for s in kr_stock_data_list if s.get("opm_pct") is not None)
    n_kr_hl = sum(1 for s in kr_stock_data_list if s.get("headlines"))
    n_kr_per = sum(1 for s in kr_stock_data_list if s.get("per") is not None)
    n_kr_pbr = sum(1 for s in kr_stock_data_list if s.get("pbr") is not None)
    n_kr_roe = sum(1 for s in kr_stock_data_list if s.get("roe_pct") is not None)
    n_kr_yoy = sum(1 for s in kr_stock_data_list if s.get("yoy_pct") is not None)
    n_kr_cons = sum(1 for s in kr_stock_data_list if s.get("consensus_line"))
    log.info("  한국 데이터 소스: Fnguide(SVD_Main, 실적이슈·시세현황·목표가·컨센서스·Business Summary)")
    log.info("  한국 수집 결과: 총 %d종목 | 현재가 %d 목표가 %d OPM %d PER %d PBR %d ROE %d 전년대비 %d 컨센서스 %d 리포트 %d | 캐시 %d 신규 %d", len(kr_stock_data_list), n_kr_price, n_kr_target, n_kr_opm, n_kr_per, n_kr_pbr, n_kr_roe, n_kr_yoy, n_kr_cons, n_kr_hl, kr_cache_hits, len(kr_stock_data_list) - kr_cache_hits)
    if kr_stock_data_list:
        s0 = kr_stock_data_list[0]
        log.debug("  한국 수집 샘플(첫 종목): %s | 현재가=%s 목표가=%s OPM=%s PER=%s PBR=%s ROE=%s 전년대비=%s 컨센서스=%s", s0.get("ticker"), s0.get("current_price"), s0.get("target_price"), s0.get("opm_pct"), s0.get("per"), s0.get("pbr"), s0.get("roe_pct"), s0.get("yoy_pct"), (s0.get("consensus_line") or "")[:40])

    def _compute_quant_score(s: dict) -> tuple[float, str]:
        """공식으로 계산 가능한 지표만 사용해 0~100 퀀트 점수. (괴리·OPM·PER·PBR·ROE)"""
        score = 40.0
        reason_parts = []
        try:
            cp = float(s.get("current_price") or 0)
            tp = float(s.get("target_price") or 0)
            if cp > 0 and tp > 0:
                gap = (tp - cp) / cp * 100
                if gap >= 20:
                    score += 25
                    reason_parts.append("괴리%.0f%%" % gap)
                elif gap >= 10:
                    score += 15
                    reason_parts.append("괴리%.0f%%" % gap)
        except (TypeError, ValueError):
            pass
        try:
            opm = float(s.get("opm_pct") or 0)
            if opm >= 99:
                reason_parts.append("OPM(과대·확인)")
            elif opm >= 10:
                score += 25
                reason_parts.append("OPM%.0f%%" % opm)
            elif opm >= 0:
                score += 10
                reason_parts.append("OPM%.0f%%" % opm)
        except (TypeError, ValueError):
            pass
        try:
            per = s.get("per") is not None and float(s["per"]) or None
            if per is not None and 0 < per < 1000:
                if per < 10:
                    score += 12
                    reason_parts.append("PER%.1f" % per)
                elif per < 15:
                    score += 8
                    reason_parts.append("PER%.1f" % per)
                elif per < 25:
                    score += 4
                if per > 80:
                    score -= 5
        except (TypeError, ValueError):
            pass
        try:
            pbr = s.get("pbr") is not None and float(s["pbr"]) or None
            if pbr is not None and 0 < pbr < 1000:
                if pbr < 1:
                    score += 8
                    reason_parts.append("PBR%.2f" % pbr)
                elif pbr < 2:
                    score += 4
        except (TypeError, ValueError):
            pass
        try:
            roe = s.get("roe_pct") is not None and float(s["roe_pct"]) or None
            if roe is not None and -100 < roe < 1000:
                if roe >= 20:
                    score += 10
                    reason_parts.append("ROE%.0f%%" % roe)
                elif roe >= 15:
                    score += 6
                elif roe >= 10:
                    score += 3
        except (TypeError, ValueError):
            pass
        reason = ", ".join(reason_parts) if reason_parts else "괴리·OPM·PER·PBR·ROE 기준"
        return min(98.0, max(0.0, score)), reason

    def _fallback_score(s: dict):
        """API 미사용 시 퀀트 점수(괴리·OPM·PER·PBR·ROE)로 0~100."""
        return _compute_quant_score(s)

    stock_top10_us = []
    stock_top10_kr = []
    stock_fallback_reason_us: Optional[str] = None
    stock_fallback_reason_kr: Optional[str] = None
    if GEMINI_API_KEY:
        to_send_us = us_stock_data_list[:50]
        to_send_kr = kr_stock_data_list[:50]
        for s in to_send_us + to_send_kr:
            sc, re = _compute_quant_score(s)
            s["quant_score"] = round(sc, 1)
            s["quant_reason"] = re
            log.debug("  [퀀트 산정] %s %s | 현재가=%s 목표가=%s OPM=%s PER=%s PBR=%s ROE=%s → 점수=%.1f (%s)", s.get("ticker"), s.get("name"), s.get("current_price"), s.get("target_price"), s.get("opm_pct"), s.get("per"), s.get("pbr"), s.get("roe_pct"), sc, re)
        us_by_score = sorted(to_send_us, key=lambda x: -(x.get("quant_score") or 0))[:5]
        kr_by_score = sorted(to_send_kr, key=lambda x: -(x.get("quant_score") or 0))[:5]
        log.info("  퀀트 점수 산정 완료 (미국 상위 5): %s", ", ".join("%s %.1f(%s)" % (s["ticker"], s.get("quant_score", 0), (s.get("quant_reason") or "")[:30]) for s in us_by_score))
        log.info("  퀀트 점수 산정 완료 (한국 상위 5): %s", ", ".join("%s %.1f(%s)" % (s["ticker"], s.get("quant_score", 0), (s.get("quant_reason") or "")[:30]) for s in kr_by_score))
        log.info("  Gemini 종목분석 입력: 미국 %d종목, 한국 %d종목 (배치 %d개씩, 배치 간 %ds 대기)", len(to_send_us), len(to_send_kr), BATCH_SIZE, GEMINI_SLEEP_SEC)
        log.info("  Gemini에 보내는 항목: 퀀트점수(괴리·OPM·PER·PBR·ROE) + ticker, 현재가, 목표가, OPM%%, PER/PBR/ROE, 헤드라인 → Sentiment 반영 후 TOP 10")
        stock_top10_us, err_us = batch_stock_analysis_with_scores(
            to_send_us, GEMINI_API_KEY, BATCH_SIZE, GEMINI_SLEEP_SEC, "US"
        )
        if err_us:
            log.warning("  미국 종목분석 API 에러: %s", err_us[:400])
            stock_fallback_reason_us = "Gemini 종목분석 API 실패(429/에러 등): %s" % (err_us[:200] or "알 수 없음")
        elif not stock_top10_us:
            stock_fallback_reason_us = "Gemini 종목분석 응답이 빈 배열(파싱 결과 0건)이라 API 결과 미사용"
        else:
            log.info("  미국 종목분석 Gemini 결과: TOP %d (ticker, score, reason)", len(stock_top10_us))
            for i, r in enumerate(stock_top10_us[:5], 1):
                log.debug("    미국 #%d %s score=%s %s", i, r.get("ticker"), r.get("score"), (r.get("reason") or "")[:80])
        time.sleep(GEMINI_SLEEP_SEC)
        stock_top10_kr, err_kr = batch_stock_analysis_with_scores(
            to_send_kr, GEMINI_API_KEY, BATCH_SIZE, GEMINI_SLEEP_SEC, "KR"
        )
        if err_kr:
            log.warning("  한국 종목분석 API 에러: %s", err_kr[:400])
            stock_fallback_reason_kr = "Gemini 종목분석 API 실패(429/에러 등): %s" % (err_kr[:200] or "알 수 없음")
        elif not stock_top10_kr:
            stock_fallback_reason_kr = "Gemini 종목분석 응답이 빈 배열(파싱 결과 0건)이라 API 결과 미사용"
        else:
            log.info("  한국 종목분석 Gemini 결과: TOP %d (ticker, score, reason)", len(stock_top10_kr))
            for i, r in enumerate(stock_top10_kr[:5], 1):
                log.debug("    한국 #%d %s score=%s %s", i, r.get("ticker"), r.get("score"), (r.get("reason") or "")[:80])
    else:
        stock_fallback_reason_us = "Gemini API 키 없음(GEMINI_API_KEY 미설정)"
        stock_fallback_reason_kr = "Gemini API 키 없음(GEMINI_API_KEY 미설정)"

    if not stock_top10_us and us_stock_data_list:
        log.info("  미국 종목 TOP10: API 미사용 → 퀀트 점수(괴리·OPM·PER·PBR·ROE) 폴백으로 상위 10개 채움")
        log.info("  [API 미사용 사유] 미국 종목분석: %s", stock_fallback_reason_us or "API 호출 안 함 또는 결과 없음")
        us_scored = [(_compute_quant_score(s), s) for s in us_stock_data_list]
        us_scored.sort(key=lambda x: -x[0][0])
        for (sc, re), s in us_scored[:10]:
            log.debug("  [퀀트 폴백] 미국 %s | 현재가=%s 목표가=%s OPM=%s PER=%s PBR=%s ROE=%s → %.1f (%s)", s.get("ticker"), s.get("current_price"), s.get("target_price"), s.get("opm_pct"), s.get("per"), s.get("pbr"), s.get("roe_pct"), sc, re)
            stock_top10_us.append({"ticker": s["ticker"], "name": s["name"], "score": sc, "reason": re, "market": "US"})
    if not stock_top10_kr and kr_stock_data_list:
        log.info("  한국 종목 TOP10: API 미사용 → 퀀트 점수(괴리·OPM·PER·PBR·ROE) 폴백으로 상위 10개 채움")
        log.info("  [API 미사용 사유] 한국 종목분석: %s", stock_fallback_reason_kr or "API 호출 안 함 또는 결과 없음")
        kr_scored = [(_compute_quant_score(s), s) for s in kr_stock_data_list]
        kr_scored.sort(key=lambda x: -x[0][0])
        for (sc, re), s in kr_scored[:10]:
            log.debug("  [퀀트 폴백] 한국 %s | 현재가=%s 목표가=%s OPM=%s PER=%s PBR=%s ROE=%s → %.1f (%s)", s.get("ticker"), s.get("current_price"), s.get("target_price"), s.get("opm_pct"), s.get("per"), s.get("pbr"), s.get("roe_pct"), sc, re)
            stock_top10_kr.append({"ticker": s["ticker"], "name": s["name"], "score": sc, "reason": re, "market": "KR"})

    # --- 5. 차트 분석: 정배열·골드크로스·이격도·RSI → 규칙/Gemini TOP 10 ---
    log.info("[5/6] 차트 분석: 50/100/200 정배열·골드크로스·이격도·RSI 30 이하 → TOP 10")
    log.info("  차트 요약 항목: symbol, name, alignment_50_100_200, golden_cross_50_200, displacement_200, rsi")
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
    chart_fallback_reason_us: Optional[str] = None
    chart_fallback_reason_kr: Optional[str] = None
    log.info("  Gemini 차트분석 입력: 미국 %d개, 한국 %d개 요약 (정배열·골드크로스·이격도·RSI) → 상위 10개 선별", len(chart_summary_us[:50]), len(chart_summary_kr[:50]))
    if GEMINI_API_KEY and chart_summary_us:
        chart_top10_us, err_ch_us = batch_chart_analysis_top10(
            chart_summary_us[:50], GEMINI_API_KEY, BATCH_SIZE, GEMINI_SLEEP_SEC, "US"
        )
        if err_ch_us:
            log.warning("  미국 차트분석 API 에러: %s", err_ch_us[:400])
            chart_fallback_reason_us = "Gemini 차트분석 API 실패: %s" % (err_ch_us[:200] or "알 수 없음")
        elif not chart_top10_us:
            chart_fallback_reason_us = "Gemini 차트분석 응답이 빈 배열(파싱 결과 0건)이라 API 결과 미사용"
        else:
            log.info("  미국 차트분석 Gemini 결과: TOP %d (symbol, reason)", len(chart_top10_us))
            for i, r in enumerate(chart_top10_us[:3], 1):
                log.debug("    미국 차트 #%d %s %s", i, r.get("symbol"), (r.get("reason") or "")[:80])
    else:
        if not GEMINI_API_KEY:
            chart_fallback_reason_us = "Gemini API 키 없음(GEMINI_API_KEY 미설정)"
    if GEMINI_API_KEY and chart_summary_kr:
        chart_top10_kr, err_ch_kr = batch_chart_analysis_top10(
            chart_summary_kr[:50], GEMINI_API_KEY, BATCH_SIZE, GEMINI_SLEEP_SEC, "KR"
        )
        if err_ch_kr:
            log.warning("  한국 차트분석 API 에러: %s", err_ch_kr[:400])
            chart_fallback_reason_kr = "Gemini 차트분석 API 실패: %s" % (err_ch_kr[:200] or "알 수 없음")
        elif not chart_top10_kr:
            chart_fallback_reason_kr = "Gemini 차트분석 응답이 빈 배열(파싱 결과 0건)이라 API 결과 미사용"
        else:
            log.info("  한국 차트분석 Gemini 결과: TOP %d (symbol, reason)", len(chart_top10_kr))
            for i, r in enumerate(chart_top10_kr[:3], 1):
                log.debug("    한국 차트 #%d %s %s", i, r.get("symbol"), (r.get("reason") or "")[:80])
    else:
        if not GEMINI_API_KEY:
            chart_fallback_reason_kr = "Gemini API 키 없음(GEMINI_API_KEY 미설정)"
    if not chart_top10_us:
        log.info("  미국 차트 TOP10: API 미사용 → 규칙 기반(정배열·골드크로스·이격도·RSI 30 이하)으로 10개 선정")
        log.info("  [API 미사용 사유] 미국 차트분석: %s", chart_fallback_reason_us or "API 호출 안 함 또는 결과 없음")
        chart_top10_us = _chart_top10_by_rule(us_candidates, us_names, "US")
    if not chart_top10_kr:
        log.info("  한국 차트 TOP10: API 미사용 → 규칙 기반으로 10개 선정")
        log.info("  [API 미사용 사유] 한국 차트분석: %s", chart_fallback_reason_kr or "API 호출 안 함 또는 결과 없음")
        chart_top10_kr = _chart_top10_by_rule(kr_candidates, kr_names, "KR")

    # --- 6. 텔레그램 포맷 (HTML, 날짜·섹션 구분) ---
    log.info("[6/6] 텔레그램 전송")
    def esc(t):
        t = (t or "").replace("```", "").replace("&", "＆").replace("<", "＜").replace(">", "＞")
        return t[:250]

    report_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    parts = [
        "📊 <b>AI 투자 비서</b>",
        "📅 " + report_date,
        "",
        "▸ <b>1. 종목 분석</b> (퀀트+Sentiment TOP10)",
        "",
        "🇰🇷 <b>한국</b>",
    ]
    for i, r in enumerate(stock_top10_kr[:10], 1):
        parts.append("  %d. %s <code>%s</code> · %s\n     <i>%s</i>" % (i, esc(r.get("name")), r.get("ticker", ""), r.get("score"), esc(r.get("reason"))))
    parts.append("")
    parts.append("🇺🇸 <b>미국</b>")
    for i, r in enumerate(stock_top10_us[:10], 1):
        parts.append("  %d. %s <code>%s</code> · %s\n     <i>%s</i>" % (i, esc(r.get("name")), r.get("ticker", ""), r.get("score"), esc(r.get("reason"))))
    parts.extend([
        "",
        "▸ <b>2. 차트 분석</b> (정배열·골드크로스·이격도·RSI TOP10)",
        "",
        "🇰🇷 <b>한국</b>",
    ])
    for i, r in enumerate(chart_top10_kr[:10], 1):
        parts.append("  %d. %s <code>%s</code>\n     <i>%s</i>" % (i, esc(r.get("name")), r.get("symbol", ""), esc(r.get("reason"))))
    parts.append("")
    parts.append("🇺🇸 <b>미국</b>")
    for i, r in enumerate(chart_top10_us[:10], 1):
        parts.append("  %d. %s <code>%s</code>\n     <i>%s</i>" % (i, esc(r.get("name")), r.get("symbol", ""), esc(r.get("reason"))))
    parts.append("")
    parts.append("— 퀀트·차트 기반 참고용, 투자 책임은 본인에게 있습니다 —")

    message = "\n".join(parts)
    chunk = 4000
    if len(message) > chunk:
        n_chunks = (len(message) + chunk - 1) // chunk
        log.info("  텔레그램: 메시지 %d자 → %d개 청크로 전송", len(message), n_chunks)
        for i in range(0, len(message), chunk):
            ok = send_telegram(message[i : i + chunk], TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
            log.info("  텔레그램 청크 %d/%d: %s", (i // chunk) + 1, n_chunks, "성공" if ok else "실패")
            time.sleep(1)
    else:
        ok = send_telegram(message, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
        log.info("  텔레그램 전송: %s (메시지 %d자)", "성공" if ok else "실패", len(message))

    # 저장
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = OUTPUT_DIR / "daily_report.json"
    report = {
        "stock_analysis_kr": stock_top10_kr,
        "stock_analysis_us": stock_top10_us,
        "chart_analysis_kr": chart_top10_kr,
        "chart_analysis_us": chart_top10_us,
    }
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    log.info("  저장: %s (종목 TOP10 미국/한국, 차트 TOP10 미국/한국)", report_path)
    log.info("  완료. 로그 파일: %s", log_path)


if __name__ == "__main__":
    run()
