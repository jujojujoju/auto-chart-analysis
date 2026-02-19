# -*- coding: utf-8 -*-
"""1차 기계적 필터: AI 후보를 50개 이하로 압축.

기준: 거래량 급증 + OPM 10% 이상 + 골든크로스 등.
"""

from typing import Any, Dict, List, Optional

import pandas as pd

from .indicators import (
    add_sma_50_100_200,
    alignment_50_100_200,
    displacement_200,
    golden_cross_recent,
)
from .ohlcv_processor import add_technical_indicators


def _safe_float(v: Any) -> float:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return 0.0
    try:
        x = float(v)
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


def volume_surge(df: pd.DataFrame, mult: float = 1.2, days: int = 5) -> bool:
    """최근 days일 평균 거래량이 20일 평균 대비 mult 배 이상."""
    if len(df) < 20 or "Volume" not in df.columns:
        return False
    recent_vol = df["Volume"].tail(days).mean()
    avg20 = df["Volume"].tail(20).mean()
    if avg20 and avg20 > 0:
        return recent_vol >= mult * avg20
    return False


def filter_chart_candidates(
    charts: List[dict],
    max_candidates: int = 50,
    displacement_min: float = 0.85,
    displacement_max: float = 1.20,
) -> List[dict]:
    """차트 리스트에서 골든크로스/정배열 + 이격도 적정인 종목만 남겨 max_candidates개까지.

    charts: [{"symbol", "ohlcv": {date: {Close, Volume, ...}}}, ...]
    ohlcv에 sma_50, sma_100, sma_200, rsi 있어야 함. 없으면 여기서 추가 계산 시도.
    """
    scored: List[tuple] = []
    for ch in charts:
        ohlcv = ch.get("ohlcv", {})
        if not ohlcv:
            continue
        df = pd.DataFrame.from_dict(ohlcv, orient="index")
        if df.empty or len(df) < 200:
            continue
        for c in ["Open", "High", "Low", "Close", "Volume"]:
            if c not in df.columns:
                continue
        df.index = pd.to_datetime(df.index, errors="coerce")
        df = df.sort_index()
        df = add_technical_indicators(df)
        df = add_sma_50_100_200(df)

        gold = golden_cross_recent(df, "sma_50", "sma_200", 20)
        align = alignment_50_100_200(df)
        disp = displacement_200(df)
        vol_ok = volume_surge(df, 1.2, 5)

        if disp is not None and (disp < displacement_min or disp > displacement_max):
            continue
        if not gold and not align:
            continue

        score = 0
        if gold:
            score += 2
        if align:
            score += 2
        if vol_ok:
            score += 1
        if disp is not None and 0.95 <= disp <= 1.08:
            score += 1
        scored.append((score, ch))

    scored.sort(key=lambda x: -x[0])
    return [ch for _, ch in scored[:max_candidates]]


def filter_chart_candidates_from_dfs(
    symbol_dfs: List[tuple],
    max_candidates: int = 50,
    displacement_min: float = 0.85,
    displacement_max: float = 1.20,
) -> List[str]:
    """(symbol, df) 리스트에서 후보 심볼만 반환. df는 이미 SMA 50/100/200 포함 가정."""
    scored: List[tuple] = []
    for symbol, df in symbol_dfs:
        if df is None or len(df) < 200:
            continue
        df = add_sma_50_100_200(df)
        gold = golden_cross_recent(df, "sma_50", "sma_200", 20)
        align = alignment_50_100_200(df)
        disp = displacement_200(df)
        vol_ok = volume_surge(df, 1.2, 5)
        if disp is not None and (disp < displacement_min or disp > displacement_max):
            continue
        if not gold and not align:
            continue
        score = (2 if gold else 0) + (2 if align else 0) + (1 if vol_ok else 0)
        scored.append((score, symbol))
    scored.sort(key=lambda x: -x[0])
    return [s for _, s in scored[:max_candidates]]
