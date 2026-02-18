# -*- coding: utf-8 -*-
"""국장(한국) 종목 리스트 + 종목명 매핑. KOSPI/KOSDAQ 캐싱."""

import json
from pathlib import Path
from typing import List, Tuple

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
