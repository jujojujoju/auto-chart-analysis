# -*- coding: utf-8 -*-
"""50/100/200 이평선, 골든/데드 크로스, 정배열, 200 이격도 계산."""

from typing import Any, Optional

import pandas as pd


def _safe_float(v: Any) -> float:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return 0.0
    try:
        x = float(v)
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


def add_sma_50_100_200(df: pd.DataFrame) -> pd.DataFrame:
    """DataFrame에 sma_50, sma_100, sma_200 없으면 추가."""
    out = df.copy()
    if "sma_50" not in out.columns:
        out["sma_50"] = out["Close"].rolling(50, min_periods=1).mean()
    if "sma_100" not in out.columns:
        out["sma_100"] = out["Close"].rolling(100, min_periods=1).mean()
    if "sma_200" not in out.columns:
        out["sma_200"] = out["Close"].rolling(200, min_periods=1).mean()
    return out


def golden_cross_recent(df: pd.DataFrame, short: str = "sma_50", long: str = "sma_200", days: int = 20) -> bool:
    """최근 days일 내 단기선이 장기선을 상향 돌파(골든크로스) 발생 여부."""
    if len(df) < 2 or short not in df.columns or long not in df.columns:
        return False
    recent = df.tail(days + 1)
    prev_below = (recent[short].shift(1) <= recent[long].shift(1)).fillna(False)
    curr_above = (recent[short] > recent[long])
    return bool((prev_below & curr_above).any())


def dead_cross_recent(df: pd.DataFrame, short: str = "sma_50", long: str = "sma_200", days: int = 20) -> bool:
    """최근 days일 내 단기선이 장기선을 하향 돌파(데드크로스) 발생 여부."""
    if len(df) < 2 or short not in df.columns or long not in df.columns:
        return False
    recent = df.tail(days + 1)
    prev_above = (recent[short].shift(1) >= recent[long].shift(1)).fillna(False)
    curr_below = (recent[short] < recent[long])
    return bool((prev_above & curr_below).any())


def alignment_50_100_200(df: pd.DataFrame) -> bool:
    """현재 봉 기준 정배열: sma_50 > sma_100 > sma_200."""
    if len(df) < 1:
        return False
    row = df.iloc[-1]
    s50 = _safe_float(row.get("sma_50"))
    s100 = _safe_float(row.get("sma_100"))
    s200 = _safe_float(row.get("sma_200"))
    if s200 <= 0:
        return False
    return s50 > s100 > s200


def displacement_200(df: pd.DataFrame) -> Optional[float]:
    """현재 종가 / 200일선 비율(이격도). None if N/A."""
    if len(df) < 1:
        return None
    row = df.iloc[-1]
    c = _safe_float(row.get("Close"))
    s200 = _safe_float(row.get("sma_200"))
    if s200 <= 0:
        return None
    return round(c / s200, 4)


def chart_indicators(df: pd.DataFrame) -> dict:
    """한 종목 OHLCV DataFrame에 대해 50/100/200 관련 지표 일괄 계산."""
    df = add_sma_50_100_200(df)
    return {
        "golden_cross_50_200": golden_cross_recent(df, "sma_50", "sma_200", 20),
        "dead_cross_50_200": dead_cross_recent(df, "sma_50", "sma_200", 20),
        "alignment_50_100_200": alignment_50_100_200(df),
        "displacement_200": displacement_200(df),
        "rsi": _safe_float(df.iloc[-1].get("rsi")) if "rsi" in df.columns else None,
        "close": _safe_float(df.iloc[-1].get("Close")),
        "sma_50": _safe_float(df.iloc[-1].get("sma_50")),
        "sma_200": _safe_float(df.iloc[-1].get("sma_200")),
    }


def chart_score_for_filter(
    df: pd.DataFrame,
    displacement_min: float = 0.85,
    displacement_max: float = 1.20,
    rsi_bullish_under: float = 30,
) -> tuple[float, bool]:
    """차트 분석용 점수 (높을수록 좋음) 및 통과 여부.
    정배열+골드크로스+이격도 적정+정배열인데 RSI 30 이하 가산.
    """
    df = add_sma_50_100_200(df)
    score = 0.0
    align = alignment_50_100_200(df)
    gold = golden_cross_recent(df, "sma_50", "sma_200", 20)
    disp = displacement_200(df)
    rsi = _safe_float(df.iloc[-1].get("rsi")) if "rsi" in df.columns else None
    if align:
        score += 2.0
    if gold:
        score += 2.0
    if disp is not None and displacement_min <= disp <= displacement_max:
        score += 1.0
    if align and rsi is not None and rsi <= rsi_bullish_under:
        score += 1.5
    ok = align and gold and (disp is not None and displacement_min <= disp <= displacement_max)
    return score, ok
