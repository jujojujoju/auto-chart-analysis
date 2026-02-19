# -*- coding: utf-8 -*-
"""차트 데이터 압축 - 1회 Gemini 호출용.

- compress_chart: 절대 가격 (레거시)
- compress_chart_normalized: 정규화(변동률·이격도) → Gemini에 권장.
"""

import math
from typing import Any, Optional


def _safe_float(v: Any) -> float:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def compress_chart_normalized(
    chart: dict,
    name: str = "",
    normalized: Optional[dict] = None,
) -> str:
    """종목당 1줄 요약 (정규화). Gemini에 줄 때 권장.

    절대 가격 대신: 전일 대비 변동률(%), 주가/20일선·60일선 비율(이격도).
    normalized가 없으면 chart_normalize.compute_normalized(chart) 호출.
    """
    from .chart_normalize import compute_normalized

    symbol = chart.get("symbol", "?")
    norm = normalized if normalized is not None else compute_normalized(chart)
    if not norm.get("10d_pct") and not norm.get("10d_c_s20"):
        return "%s %s: no_data" % (symbol, name or symbol)

    c_s20 = norm.get("last_c_s20", 0) or 0
    c_s60 = norm.get("last_c_s60", 0) or 0
    rsi = norm.get("rsi", 0) or 0
    pct = norm.get("10d_pct", [])
    c_s20_series = norm.get("10d_c_s20", [])

    pct_s = ",".join("%.1f%%" % x for x in pct[-10:]) if pct else ""
    c_s20_s = ",".join("%.3f" % x for x in c_s20_series[-10:]) if c_s20_series else ""
    return "%s %s: C/s20=%.3f C/s60=%.3f rsi=%.0f | 10d_pct=[%s] 10d_c/s20=[%s]" % (
        symbol,
        name or symbol,
        c_s20,
        c_s60,
        rsi,
        pct_s,
        c_s20_s,
    )


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
    """전체 차트를 한 블록 텍스트로 압축 (1회 Gemini 호출용, 절대 가격)."""
    lines = []
    for ch in charts:
        sym = ch.get("symbol", "?")
        name = ticker_names.get(sym, sym)
        lines.append(compress_chart(ch, name))
    return "\n".join(lines)


def compress_all_charts_normalized(
    charts: list[dict],
    ticker_names: dict[str, str],
    normalized_cache: Optional[dict[str, dict]] = None,
) -> str:
    """전체 차트를 정규화된 1줄씩 압축 (Gemini 권장). normalized_cache: symbol -> normalized dict."""
    from .chart_normalize import compute_normalized

    lines = []
    for ch in charts:
        sym = ch.get("symbol", "?")
        name = ticker_names.get(sym, sym)
        norm = (normalized_cache or {}).get(sym) or compute_normalized(ch)
        lines.append(compress_chart_normalized(ch, name, normalized=norm))
    return "\n".join(lines)
