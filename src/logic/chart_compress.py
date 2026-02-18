# -*- coding: utf-8 -*-
"""차트 데이터 압축 - 1회 Gemini 호출용."""

import math
from typing import Any


def _safe_float(v: Any) -> float:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def compress_chart(chart: dict, name: str = "") -> str:
    """종목당 1줄 요약. symbol name: C=X s5=X s20=X s60=X rsi=X | 10d_closes=[...]"""
    symbol = chart.get("symbol", "?")
    ohlcv = chart.get("ohlcv", {})
    if not ohlcv:
        return "%s %s: no_data" % (symbol, name or symbol)
    items = list(ohlcv.items())
    last = items[-1][1] if items else {}
    closes = []
    for _, row in items[-10:]:
        if isinstance(row, dict) and "Close" in row:
            v = row["Close"]
            if v is not None and not (isinstance(v, float) and math.isnan(v)):
                closes.append(int(v) if isinstance(v, (int, float)) and v == int(v) else v)
    c = _safe_float(last.get("Close"))
    s5 = _safe_float(last.get("sma_5"))
    s20 = _safe_float(last.get("sma_20"))
    s60 = _safe_float(last.get("sma_60"))
    rsi = _safe_float(last.get("rsi"))
    vol = last.get("Volume", 0)
    if isinstance(vol, (int, float)) and vol >= 1e6:
        vol_s = "%.1fM" % (vol / 1e6)
    elif isinstance(vol, (int, float)) and vol >= 1e3:
        vol_s = "%.1fK" % (vol / 1e3)
    else:
        vol_s = str(vol)
    return "%s %s: C=%.0f s5=%.0f s20=%.0f s60=%.0f rsi=%.0f v=%s | 10d=%s" % (
        symbol, name or symbol, c, s5, s20, s60, rsi, vol_s, closes[-10:] if closes else []
    )


def compress_all_charts(charts: list[dict], ticker_names: dict[str, str]) -> str:
    """전체 차트를 한 블록 텍스트로 압축 (1회 Gemini 호출용)."""
    lines = []
    for ch in charts:
        sym = ch.get("symbol", "?")
        name = ticker_names.get(sym, sym)
        lines.append(compress_chart(ch, name))
    return "\n".join(lines)
