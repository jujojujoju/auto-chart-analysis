# -*- coding: utf-8 -*-
"""규칙 기반 차트 패턴 매칭. (Gemini 없이)

사용자가 정의한 정답 패턴을 규칙으로 저장하고,
OHLCV+지표만으로 적합 종목을 필터링.

[정답 패턴]
- 하락/횡보 후 저점 상승 → 고점 돌파 직후 눌림목 (0.3~0.6 되돌림)
- 이평선 역배열 → 정배열 전환 초입
- 저점이 높아지는 횟수 최근 1번 이하
[제외]
- 이미 정배열 오래 유지, 이격 과대, RSI 70 근처
"""

from typing import Any, Optional

# 기본 파라미터 (run_pipeline·자가 테스트 공용). 조정 시 아래 주석 참고.
#
# max_higher_low_count: 저점 상승 허용 횟수. "최근 N일 안에서 저점이 전일보다 높아진 일수"가 이 값 이하인 종목만 통과.
#   작을수록 엄격(역배열→정배열 전환 초입만), 클수록 완화. 예: 1=전환 직후만, 18=거의 제한 없음.
# max_rsi: RSI 상한. 최근 5일 평균 RSI가 이 값 이하만 통과. 과매수 제외용. 낮을수록 엄격.
# sma_long_ratio: 정배열 허용 비율. (최근 long_ok_days일 중 정배열 일수/long_ok_days) < 이 값이어야 통과.
#   1에 가까우면 정배열 오래 유지해도 OK, 0에 가까우면 전환 초입만. 예: 0.6=18일 미만, 0.85=25일 미만.
# pullback_min / pullback_max: 돌파 고점 대비 되돌림 비율 범위. 이 안이어야 "돌파 후 되돌림" 인정.
#   pullback_min=0.3, max=0.6 이면 30~60% 눌림목만 허용. 0~1.0 이면 거의 제한 없음.
# lookback: 되돌림·돌파 판단에 쓰는 구간(일). 최근 lookback일만 봄.
# higher_low_lookback: 저점 상승 횟수를 셀 구간(일).
# long_ok_days: 정배열 일수를 셀 구간(일).
# displacement_sma20_min / displacement_sma20_max: 이격도(종가/20일선) 허용 범위.
#
DEFAULT_PARAMS = {
    "max_higher_low_count": 1,
    "max_rsi": 50.0,
    "sma_long_ratio": 0.85,
    "pullback_min": 0.3,
    "pullback_max": 0.6,
    "lookback": 500,
    "higher_low_lookback": 100,
    "long_ok_days": 300,
    "displacement_sma20_min": 0.85,
    "displacement_sma20_max": 1.20,
}


def _safe_float(v: Any) -> float:
    if v is None:
        return 0.0
    try:
        x = float(v)
        return x if x == x else 0.0  # nan
    except (TypeError, ValueError):
        return 0.0


def _ordered_rows(chart: dict) -> list[tuple[str, dict]]:
    """차트 ohlcv를 날짜 순 (과거→최근) 리스트로."""
    ohlcv = chart.get("ohlcv", {})
    if not ohlcv:
        return []
    items = sorted(ohlcv.items(), key=lambda x: x[0])
    return items


def _higher_low_count(rows: list[tuple[str, dict]], lookback: int = 20) -> int:
    """최근 lookback일 내에서 저점이 이전보다 높아진 횟수."""
    if len(rows) < 2 or lookback < 2:
        return 0
    recent = rows[-lookback:]
    count = 0
    for i in range(1, len(recent)):
        low_prev = _safe_float(recent[i - 1][1].get("Low"))
        low_curr = _safe_float(recent[i][1].get("Low"))
        if low_curr > low_prev and low_prev > 0:
            count += 1
    return count


def _rsi_ok(rows: list[tuple[str, dict]], max_rsi: float = 68.0, params: Optional[dict] = None) -> bool:
    """최근 5일 평균 RSI가 과매수 구간 미만."""
    if params and "max_rsi" in params:
        max_rsi = float(params["max_rsi"])
    if not rows:
        return True
    recent = rows[-5:]
    rsis = [_safe_float(r.get("rsi")) for _, r in recent]
    rsis = [x for x in rsis if 0 < x < 100]
    if not rsis:
        return True
    return sum(rsis) / len(rsis) <= max_rsi


def _sma_alignment_ok(rows: list[tuple[str, dict]], long_ok_days: int = 30, params: Optional[dict] = None) -> bool:
    """정배열(s5>s20>s60)이 오래 유지되지 않음. 최근 long_ok_days일 내 완성된 정배열 일수 적을수록 적합."""
    if params:
        long_ok_days = int(params.get("long_ok_days", long_ok_days))
        ratio = float(params.get("sma_long_ratio", 0.6))
    else:
        ratio = 0.6
    if len(rows) < 60:
        return True
    recent = rows[-long_ok_days:]
    count = 0
    for _, r in recent:
        s5 = _safe_float(r.get("sma_5"))
        s20 = _safe_float(r.get("sma_20"))
        s60 = _safe_float(r.get("sma_60"))
        if s5 > s20 > s60 and s60 > 0:
            count += 1
    return count < long_ok_days * ratio


def _displacement_ok(rows: list[tuple[str, dict]], params: Optional[dict] = None) -> bool:
    """이격도(종가/20일선)가 허용 범위 안. 너무 벌어지지 않은 종목만 통과."""
    if not rows:
        return True
    dmin = float(params.get("displacement_sma20_min", 0.85)) if params else 0.85
    dmax = float(params.get("displacement_sma20_max", 1.20)) if params else 1.20
    _, r = rows[-1]
    c = _safe_float(r.get("Close"))
    s20 = _safe_float(r.get("sma_20"))
    if not s20 or s20 <= 0:
        return True
    ratio = c / s20
    return dmin <= ratio <= dmax


def _pullback_after_breakout(rows: list[tuple[str, dict]], lookback: int = 30, params: Optional[dict] = None) -> bool:
    """최근 lookback 내 고점 돌파 후 0.3~0.6 수준 되돌림 (상승 폭 대비)."""
    pmin, pmax = 0.2, 0.7
    if params:
        lookback = int(params.get("lookback", lookback))
        pmin = float(params.get("pullback_min", 0.2))
        pmax = float(params.get("pullback_max", 0.7))
    if len(rows) < lookback:
        return False
    recent = rows[-lookback:]
    highs = [_safe_float(r.get("High")) for _, r in recent]
    lows = [_safe_float(r.get("Low")) for _, r in recent]
    closes = [_safe_float(r.get("Close")) for _, r in recent]
    if not highs or not closes:
        return False
    mid = len(recent) // 2
    prev_low = min(lows[:mid]) if mid else lows[0]
    prev_high = max(highs[:mid]) if mid else highs[0]
    recent_high = max(highs[-10:]) if len(highs) >= 10 else max(highs)
    last_close = closes[-1]
    if recent_high <= prev_low or recent_high <= prev_high:
        return False
    up_move = recent_high - prev_low
    if up_move <= 0:
        return False
    retrace = (recent_high - last_close) / up_move
    return pmin <= retrace <= pmax


def matches_pattern(chart: dict, pattern_params: Optional[dict] = None) -> tuple[bool, str]:
    """차트가 정답 패턴에 부합하는지 규칙으로 판단.

    pattern_params: None이면 DEFAULT_PARAMS 사용. 반복 학습/테스트에서 덮어쓸 수 있음.
    Returns:
        (적합 여부, 간단 사유)
    """
    params = dict(DEFAULT_PARAMS)
    if pattern_params:
        params.update(pattern_params)

    rows = _ordered_rows(chart)
    lookback = int(params.get("lookback", 30))
    if len(rows) < lookback:
        return False, "데이터 부족"

    hl_lookback = int(params.get("higher_low_lookback", 20))
    max_hl = int(params.get("max_higher_low_count", 1))
    hl_count = _higher_low_count(rows, lookback=hl_lookback)
    if hl_count > max_hl:
        return False, "저점상승 %d회(%d회 이하만 적합)" % (hl_count, max_hl)

    if not _rsi_ok(rows, max_rsi=params.get("max_rsi", 68), params=params):
        return False, "RSI 과매수 구간"

    if not _displacement_ok(rows, params=params):
        return False, "이격도 과대(20일선 대비 너무 벌어짐)"

    if not _sma_alignment_ok(rows, long_ok_days=params.get("long_ok_days", 30), params=params):
        return False, "이미 정배열 오래 유지"

    if not _pullback_after_breakout(rows, lookback=params.get("lookback", 30), params=params):
        return False, "돌파 후 되돌림 패턴 아님"

    return True, "역배열→정배열 전환 초입, 저점상승 %d회, 되돌림 구간" % hl_count


def filter_charts_by_pattern(
    charts: list[dict],
    ticker_names: dict[str, str],
    pattern_params: Optional[dict] = None,
) -> list[dict]:
    """차트 리스트에서 규칙 기반으로 정답 패턴만 추림.

    Returns:
        [{"symbol","name","chart_reason","reason"}, ...]
    """
    out = []
    for ch in charts:
        sym = ch.get("symbol", "?")
        name = ticker_names.get(sym, sym)
        ok, reason = matches_pattern(ch, pattern_params=pattern_params)
        if ok:
            out.append({
                "symbol": sym,
                "name": name,
                "chart_reason": reason,
                "reason": reason,
                "action": "",
            })
    return out
