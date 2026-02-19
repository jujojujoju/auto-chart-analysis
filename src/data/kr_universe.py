# -*- coding: utf-8 -*-
"""국장(한국) 종목 리스트 + 종목명 매핑. KOSPI/KOSDAQ 캐싱."""

import json
from pathlib import Path
from typing import List, Tuple

import pandas as pd

CACHE_FILENAME = "kr_tickers.json"


def fetch_kr_tickers_with_cache(cache_dir: Path) -> Tuple[List[str], dict]:
    """국장(KOSPI+KOSDAQ) 종목 리스트 + ticker->name 매핑. 캐시 있으면 재사용 (같은 날)."""
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    cache_path = cache_dir / CACHE_FILENAME

    if cache_path.exists():
        try:
            with open(cache_path, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("date") == today:
                return data.get("tickers", []), data.get("ticker_names", {})
        except (json.JSONDecodeError, OSError):
            pass

    tickers, names = _fetch_from_fdr()
    if tickers:
        cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump({"date": today, "tickers": tickers, "ticker_names": names}, f, indent=2, ensure_ascii=False)
        except OSError:
            pass

    return tickers, names


def _fetch_from_fdr() -> Tuple[List[str], dict]:
    """FinanceDataReader로 KOSPI+KOSDAQ 종목 리스트 조회."""
    try:
        import FinanceDataReader as fdr
    except ImportError:
        return _fallback_kr_tickers()

    tickers = []
    names = {}
    try:
        krx = fdr.StockListing("KRX")
        if krx is not None and not krx.empty:
            for _, row in krx.iterrows():
                code = str(row.get("Code", "")).strip()
                market = str(row.get("Market", "")).upper()
                name = str(row.get("Name", "")).strip()
                if not code or len(code) < 5:
                    continue
                suffix = ".KQ" if "KOSDAQ" in market else ".KS"
                t = code.zfill(6) + suffix
                tickers.append(t)
                if name:
                    names[t] = name
    except Exception:
        return _fallback_kr_tickers()

    if tickers:
        tickers = list(dict.fromkeys(tickers))
        return tickers, names
    t, n = _fallback_kr_tickers()
    return t, n


def fetch_kr_market_cap_top500(cache_dir: Path) -> Tuple[List[str], dict]:
    """시가총액 순위 500개 종목 + ticker->name. 캐시(같은 날) 재사용."""
    from datetime import datetime
    import json
    cache_path = cache_dir / "kr_market_cap_top500.json"
    today = datetime.now().strftime("%Y-%m-%d")
    if cache_path.exists():
        try:
            with open(cache_path, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("date") == today:
                return data.get("tickers", [])[:500], data.get("ticker_names", {})
        except (json.JSONDecodeError, OSError):
            pass

    try:
        import FinanceDataReader as fdr
        krx = fdr.StockListing("KRX")
        if krx is None or krx.empty:
            return fetch_kr_tickers_with_cache(cache_dir)[0][:500], {}
        # Marcap(시가총액) 기준 정렬. 컬럼명은 버전에 따라 다를 수 있음
        marcap_col = None
        for c in ["Marcap", "Market Cap", "marcap"]:
            if c in krx.columns:
                marcap_col = c
                break
        if marcap_col is None and len(krx.columns) > 0:
            marcap_col = krx.columns[krx.columns.str.contains("cap", case=False)][0] if any(krx.columns.str.contains("cap", case=False)) else None
        if marcap_col is None:
            tickers, names = _fetch_from_fdr()
            return tickers[:500], names
        krx = krx.dropna(subset=[marcap_col])
        krx[marcap_col] = pd.to_numeric(krx[marcap_col], errors="coerce").fillna(0)
        krx = krx.sort_values(marcap_col, ascending=False).head(500)
        tickers = []
        names = {}
        for _, row in krx.iterrows():
            code = str(row.get("Code", "")).strip()
            market = str(row.get("Market", "")).upper()
            name = str(row.get("Name", "")).strip()
            if not code or len(code) < 5:
                continue
            suffix = ".KQ" if "KOSDAQ" in market else ".KS"
            t = code.zfill(6) + suffix
            tickers.append(t)
            if name:
                names[t] = name
        tickers = list(dict.fromkeys(tickers))[:500]
        cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump({"date": today, "tickers": tickers, "ticker_names": names}, f, indent=2, ensure_ascii=False)
        except OSError:
            pass
        return tickers, names
    except Exception:
        return fetch_kr_tickers_with_cache(cache_dir)[0][:500], {}


def _fallback_kr_tickers() -> Tuple[List[str], dict]:
    """FinanceDataReader 미설치/실패 시 기본 종목 리스트."""
    t = [
        "005930.KS", "000660.KS", "035420.KS", "035720.KS", "051910.KS",
        "006400.KS", "003670.KS", "068270.KS", "207940.KS", "005380.KS",
        "000270.KS", "012330.KS", "105560.KS", "055550.KS", "066570.KS",
        "030210.KS", "079160.KS",
    ]
    n = {s: s.split(".")[0] for s in t}
    return t, n
