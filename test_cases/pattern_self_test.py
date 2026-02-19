#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""규칙 기반 패턴의 자가 테스트: 카카오 차트 패턴(하락→이평선 돌파→저점 상승→횡보)과의 유사도를
수치로 평가하고, 유사해질 때까지 파라미터를 조정하며 최대 5회 반복.
국내 일봉 기준, 캐시 사용 가능.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import CACHE_DIR
from src.data.kr_universe import fetch_kr_tickers_with_cache
from src.data.market_data import fetch_ohlcv_cached
from src.logic.ohlcv_processor import process_ohlcv_to_json
from src.logic.pattern_rules import (
    DEFAULT_PARAMS,
    filter_charts_by_pattern,
    _safe_float,
    _ordered_rows,
    _higher_low_count,
    _rsi_ok,
    _sma_alignment_ok,
    _pullback_after_breakout,
)


def _ordered_rows_from_chart(chart: dict) -> list:
    ohlcv = chart.get("ohlcv", {})
    if not ohlcv:
        return []
    return sorted(ohlcv.items(), key=lambda x: x[0])


def reference_score(chart: dict) -> float:
    """참조 패턴(카카오: 하락→이평선 돌파→저점 상승→횡보)과의 유사도 0~1.
    수치만으로 판단: (1) 전반부 하락 (2) 후반부 이평선 돌파 (3) 저점 상승 (4) 최근 횡보.
    """
    rows = _ordered_rows_from_chart(chart)
    if len(rows) < 60:
        return 0.0

    n = len(rows)
    half = n // 2
    # 1) 전반부 하락: 앞 30일 저점/고점 추세가 하락
    first_lows = [_safe_float(rows[i][1].get("Low")) for i in range(min(30, half))]
    first_highs = [_safe_float(rows[i][1].get("High")) for i in range(min(30, half))]
    first_lows = [x for x in first_lows if x > 0]
    first_highs = [x for x in first_highs if x > 0]
    s1 = 0.0
    if len(first_lows) >= 5 and len(first_highs) >= 5:
        # 단순: 첫 1/3 평균 vs 마지막 1/3 평균 → 하락이면 점수
        a, b = len(first_lows) // 3, len(first_lows) - len(first_lows) // 3
        if b > a:
            avg_early_low = sum(first_lows[:a]) / a
            avg_late_low = sum(first_lows[-a:]) / a if a else first_lows[-1]
            if avg_late_low < avg_early_low:
                s1 = 1.0
            else:
                s1 = 0.3
    else:
        s1 = 0.5

    # 2) 후반부 이평선 돌파: 최근 20일 중 s5 > s20 또는 s20 > s60 (정배열 전환)
    recent = rows[-20:]
    crossover = 0
    for _, r in recent:
        s5 = _safe_float(r.get("sma_5"))
        s20 = _safe_float(r.get("sma_20"))
        s60 = _safe_float(r.get("sma_60"))
        if s5 > 0 and s20 > 0 and s60 > 0 and (s5 > s20 or s20 > s60):
            crossover += 1
    s2 = min(1.0, crossover / 10.0) if recent else 0.0

    # 3) 저점 상승: 후반 20일 내 저점이 이전 대비 높아진 비율 (너무 많지 않게, 카카오처럼 뚜렷하지만 반복 많지 않게)
    recent_lows = [_safe_float(r.get("Low")) for _, r in rows[-20:]]
    higher_low_count = 0
    for i in range(1, len(recent_lows)):
        if recent_lows[i] > recent_lows[i - 1] and recent_lows[i - 1] > 0:
            higher_low_count += 1
    # 1~4회 정도면 참조와 유사 (너무 0이면 전환 없음, 너무 많으면 이미 상승 추세)
    if 1 <= higher_low_count <= 5:
        s3 = 1.0
    elif higher_low_count == 0:
        s3 = 0.3
    else:
        s3 = max(0.0, 1.0 - (higher_low_count - 5) * 0.2)

    # 4) 최근 횡보: 마지막 5일 고-저 범위 / 중간가 작음
    last5 = rows[-5:]
    if len(last5) >= 3:
        highs = [_safe_float(r.get("High")) for _, r in last5]
        lows = [_safe_float(r.get("Low")) for _, r in last5]
        closes = [_safe_float(r.get("Close")) for _, r in last5]
        rng = max(highs) - min(lows) if highs and lows else 0
        mid = sum(closes) / len(closes) if closes else 1
        if mid > 0 and rng / mid < 0.08:  # 8% 미만 변동
            s4 = 1.0
        elif mid > 0 and rng / mid < 0.15:
            s4 = 0.6
        else:
            s4 = 0.2
    else:
        s4 = 0.5

    return (s1 * 0.25 + s2 * 0.35 + s3 * 0.25 + s4 * 0.15)


def get_param_set(iteration: int) -> dict:
    """반복 회차별 파라미터 세트. 1회는 완화해 후보 확보, 2~5회는 참조에 맞게 조정."""
    base = dict(DEFAULT_PARAMS)
    # 1회: 완화해서 최소한 매칭이 나오게 (20일 내 저점상승 일수 많아도 허용, 되돌림 범위 넓게)
    if iteration == 1:
        base["max_higher_low_count"] = 18
        base["pullback_min"] = 0.0
        base["pullback_max"] = 1.0
        base["sma_long_ratio"] = 0.85
        base["max_rsi"] = 75.0
        return base
    if iteration == 2:
        base["max_higher_low_count"] = 4
        base["pullback_min"] = 0.1
        base["pullback_max"] = 0.85
        base["sma_long_ratio"] = 0.75
        return base
    if iteration == 3:
        base["max_higher_low_count"] = 3
        base["pullback_min"] = 0.15
        base["pullback_max"] = 0.75
        base["sma_long_ratio"] = 0.7
        return base
    if iteration == 4:
        base["max_higher_low_count"] = 3
        base["pullback_min"] = 0.2
        base["pullback_max"] = 0.7
        base["sma_long_ratio"] = 0.65
        return base
    # 5회: 참조에 가장 가까운 설정
    base["max_higher_low_count"] = 4
    base["pullback_min"] = 0.2
    base["pullback_max"] = 0.7
    base["max_rsi"] = 72.0
    base["sma_long_ratio"] = 0.7
    return base


def run_self_test(max_iterations: int = 5, ticker_limit: int = 120):
    """국내 일봉 캐시 사용, 최대 max_iterations 회 반복. 유사도 충족 시 조기 종료."""
    print("=" * 60)
    print("패턴 자가 테스트 (참조: 하락→이평선 돌파→저점 상승→횡보)")
    print("=" * 60)

    tickers, ticker_names = fetch_kr_tickers_with_cache(CACHE_DIR)
    tickers = tickers[:ticker_limit]
    print("종목 수 (테스트용):", len(tickers))

    charts = []
    for i, symbol in enumerate(tickers):
        try:
            df = fetch_ohlcv_cached(symbol, CACHE_DIR, max_days=365 * 3)
            ch = process_ohlcv_to_json(df, symbol, add_indicators=True)
            charts.append(ch)
        except Exception:
            continue
        if (i + 1) % 50 == 0:
            print("  OHLCV 처리:", i + 1, "/", len(tickers))

    print("차트 로드:", len(charts), "개")

    chart_by_symbol = {ch["symbol"]: ch for ch in charts}
    best_params = dict(DEFAULT_PARAMS)
    best_avg = 0.0
    best_matches = []
    best_iter = 0

    # 0건이면 규칙별 통과 수 진단 (1회차 완화 파라미터 기준)
    diag_params = get_param_set(1)
    pass_hl, pass_rsi, pass_sma, pass_pb = 0, 0, 0, 0
    for ch in charts:
        rows = _ordered_rows(ch)
        if len(rows) < 30:
            continue
        hl = _higher_low_count(rows, lookback=diag_params.get("higher_low_lookback", 20))
        if hl <= diag_params.get("max_higher_low_count", 5):
            pass_hl += 1
        if _rsi_ok(rows, params=diag_params):
            pass_rsi += 1
        if _sma_alignment_ok(rows, params=diag_params):
            pass_sma += 1
        if _pullback_after_breakout(rows, params=diag_params):
            pass_pb += 1
    print("규칙별 통과(1회차 완화): 저점상승 %d, RSI %d, 정배열비 %d, 되돌림 %d" % (pass_hl, pass_rsi, pass_sma, pass_pb))

    for iteration in range(1, max_iterations + 1):
        params = get_param_set(iteration)
        matches = filter_charts_by_pattern(charts, ticker_names, pattern_params=params)
        if not matches:
            print("[반복 %d] 파라미터 적용 → 매칭 0건. 다음 파라미터로." % iteration)
            continue

        scores = []
        for m in matches:
            sym = m.get("symbol")
            ch = chart_by_symbol.get(sym)
            if ch:
                scores.append(reference_score(ch))

        avg_score = sum(scores) / len(scores) if scores else 0.0
        max_score = max(scores) if scores else 0.0
        print("[반복 %d] 매칭 %d건, 참조 유사도 평균=%.3f 최대=%.3f" % (iteration, len(matches), avg_score, max_score))

        if avg_score > best_avg:
            best_avg = avg_score
            best_matches = matches
            best_params = params
            best_iter = iteration

        # 충분히 비슷하면 종료
        if avg_score >= 0.55 or (matches and max_score >= 0.65):
            print("→ 참조 패턴과 유사하다고 판단. 종료.")
            break
    else:
        print("→ 최대 %d회 반복 완료. 최적은 반복 %d (평균 유사도 %.3f)." % (max_iterations, best_iter, best_avg))

    # 최종 규칙에 쓰일 파라미터 출력 (pattern_rules에 반영하려면 DEFAULT_PARAMS 수정)
    print("\n권장 파라미터 (참조에 가장 가까웠던 설정):")
    for k, v in best_params.items():
        print("  %s: %s" % (k, v))
    print("\n매칭 종목 수:", len(best_matches))
    for m in best_matches[:15]:
        sym = m.get("symbol", "?")
        name = m.get("name", "?")
        reason = m.get("chart_reason", "")[:60]
        ch = chart_by_symbol.get(sym)
        ref = reference_score(ch) if ch else 0.0
        print("  %s %s 유사도=%.2f | %s" % (sym, name, ref, reason))
    if len(best_matches) > 15:
        print("  ... 외 %d건" % (len(best_matches) - 15))

    return best_params, best_matches, best_avg


if __name__ == "__main__":
    run_self_test(max_iterations=5, ticker_limit=120)
