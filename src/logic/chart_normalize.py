# -*- coding: utf-8 -*-
"""차트 정규화: 절대 가격 대신 변동률·이격도(주가/이평선)로 가공.

- AI는 7만원 vs 100만원보다 "이평선 대비 얼마나 떨어져 있는지"에 더 잘 반응.
- Gemini에 줄 때: [0.2%, -0.5%, 1.2%] (전일 대비 변동률), C/s20=1.02 (주가/20일선 비율).
- 가공 데이터는 cache/normalized_charts.json 에 저장해 재사용.
"""

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


def _safe_float(v: Any) -> float:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return 0.0
    try:
        x = float(v)
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


def compute_normalized(chart: dict) -> dict:
    """차트에서 정규화된 시계열·최근값 계산.

    Returns:
        {
            "symbol": str,
            "10d_pct": [0.2, -0.5, 1.2, ...],   # 최근 10일 전일 대비 변동률 (%)
            "10d_c_s20": [1.01, 0.99, ...],      # 최근 10일 Close/SMA20 비율
            "10d_c_s60": [0.98, 1.00, ...],      # 최근 10일 Close/SMA60 비율
            "last_c_s20": float,                 # 최근 종가/20일선
            "last_c_s60": float,                 # 최근 종가/60일선
            "rsi": float,
        }
    """
    ohlcv = chart.get("ohlcv", {})
    if not ohlcv:
        return {"symbol": chart.get("symbol", "?"), "10d_pct": [], "10d_c_s20": [], "10d_c_s60": [], "last_c_s20": 0.0, "last_c_s60": 0.0, "rsi": 0.0}

    items = sorted(ohlcv.items(), key=lambda x: x[0])
    symbol = chart.get("symbol", "?")
    out = {
        "symbol": symbol,
        "10d_pct": [],
        "10d_c_s20": [],
        "10d_c_s60": [],
        "last_c_s20": 0.0,
        "last_c_s60": 0.0,
        "rsi": 0.0,
    }

    # 최근 11일 필요 (10개 변동률을 위해)
    recent = items[-11:] if len(items) >= 11 else items
    if len(recent) < 2:
        if items:
            r = items[-1][1]
            s20 = _safe_float(r.get("sma_20"))
            s60 = _safe_float(r.get("sma_60"))
            c = _safe_float(r.get("Close"))
            out["last_c_s20"] = c / s20 if s20 and s20 > 0 else 0.0
            out["last_c_s60"] = c / s60 if s60 and s60 > 0 else 0.0
            out["rsi"] = _safe_float(r.get("rsi"))
        return out

    for i in range(1, len(recent)):
        _, curr = recent[i]
        _, prev = recent[i - 1]
        c_curr = _safe_float(curr.get("Close"))
        c_prev = _safe_float(prev.get("Close"))
        if c_prev and c_prev > 0:
            pct = (c_curr - c_prev) / c_prev * 100.0
            out["10d_pct"].append(round(pct, 2))
        s20 = _safe_float(curr.get("sma_20"))
        s60 = _safe_float(curr.get("sma_60"))
        if s20 and s20 > 0:
            out["10d_c_s20"].append(round(c_curr / s20, 4))
        if s60 and s60 > 0:
            out["10d_c_s60"].append(round(c_curr / s60, 4))

    last = recent[-1][1]
    c = _safe_float(last.get("Close"))
    s20 = _safe_float(last.get("sma_20"))
    s60 = _safe_float(last.get("sma_60"))
    out["last_c_s20"] = round(c / s20, 4) if s20 and s20 > 0 else 0.0
    out["last_c_s60"] = round(c / s60, 4) if s60 and s60 > 0 else 0.0
    out["rsi"] = round(_safe_float(last.get("rsi")), 1)
    return out


NORMALIZED_CACHE_FILENAME = "normalized_charts.json"


def load_normalized_cache(cache_dir: Path) -> Optional[dict[str, dict]]:
    """오늘 날짜의 정규화 캐시 로드. { symbol: normalized_dict } 또는 None."""
    path = (cache_dir / "normalized") / NORMALIZED_CACHE_FILENAME
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        today = datetime.now().strftime("%Y-%m-%d")
        if data.get("date") != today:
            return None
        return data.get("data") or {}
    except (json.JSONDecodeError, OSError):
        return None


def save_normalized_cache(cache_dir: Path, data: dict[str, dict]) -> None:
    """정규화 데이터 캐시 저장. data: { symbol: normalized_dict }."""
    path = (cache_dir / "normalized") / NORMALIZED_CACHE_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        payload = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "data": data,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def get_normalized_charts_cached(
    charts: list[dict],
    cache_dir: Path,
) -> dict[str, dict]:
    """캐시에서 로드 또는 계산 후 캐시 저장. { symbol: normalized_dict }."""
    cached = load_normalized_cache(cache_dir)
    symbols = {ch.get("symbol") for ch in charts if ch.get("symbol")}
    if cached and symbols and symbols <= set(cached.keys()):
        return {s: cached[s] for s in symbols if s in cached}
    out = {}
    for ch in charts:
        sym = ch.get("symbol")
        if not sym:
            continue
        out[sym] = compute_normalized(ch)
    if out:
        save_normalized_cache(cache_dir, out)
    return out
