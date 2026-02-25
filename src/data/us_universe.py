# -*- coding: utf-8 -*-
"""국장(미국) 종목 리스트 수집. S&P 500 캐싱."""

import json
import re
from pathlib import Path
from typing import List, Optional

try:
    import urllib.request
    HAS_URLLIB = True
except ImportError:
    HAS_URLLIB = False

# Wikipedia S&P 500 테이블
WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
# Wikipedia 실패 시 사용할 CSV (Symbol 컬럼)
SP500_CSV_FALLBACK_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"

# 최초 500 종목 선별은 캐시 사용 안 함. 이 개수 미만이면 fallback 사용.
MIN_SP500_TICKERS = 100
TARGET_SP500_COUNT = 500


def fetch_sp500_tickers_with_cache(cache_dir: Path) -> List[str]:
    """S&P 500 종목 리스트. 최초 500 선별은 캐시 미사용, Wikipedia → 실패 시 GitHub CSV → 50종목 fallback."""
    tickers = _fetch_sp500_from_wikipedia()
    if not tickers or len(tickers) < MIN_SP500_TICKERS:
        tickers = _fetch_sp500_from_csv_fallback()
    if not tickers or len(tickers) < MIN_SP500_TICKERS:
        return _fallback_sp500()
    return tickers[:600]


def _fetch_sp500_from_wikipedia() -> List[str]:
    """Wikipedia S&P 500 페이지에서 티커 추출."""
    if not HAS_URLLIB:
        return _fallback_sp500()

    req = urllib.request.Request(WIKI_URL, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return _fallback_sp500()

    # <td>...</td> 안의 심볼 (첫 번째 테이블)
    pattern = re.compile(r"<td[^>]*><a[^>]*>([A-Z]{1,5})</a></td>")
    candidates = pattern.findall(html)
    tickers = list(dict.fromkeys(c for c in candidates if 1 <= len(c) <= 5))
    if not tickers or len(tickers) < MIN_SP500_TICKERS:
        return _fallback_sp500()
    return tickers[:600]


def _fetch_sp500_from_csv_fallback() -> List[str]:
    """GitHub S&P 500 constituents CSV에서 Symbol 컬럼만 추출 (Wikipedia 실패 시)."""
    if not HAS_URLLIB:
        return []
    req = urllib.request.Request(SP500_CSV_FALLBACK_URL, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return []
    tickers: List[str] = []
    for line in raw.strip().split("\n")[1:]:  # skip header
        part = line.split(",")
        if part:
            sym = part[0].strip().upper()
            if sym and 1 <= len(sym) <= 5 and sym.replace("-", "").replace(".", "").isalnum():
                tickers.append(sym)
    return list(dict.fromkeys(tickers))[:TARGET_SP500_COUNT] if tickers else []


def _fallback_sp500() -> List[str]:
    """네트워크 실패 시 기본 종목 리스트."""
    return [
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B", "JPM", "V",
        "JNJ", "WMT", "PG", "MA", "UNH", "HD", "DIS", "BAC", "ADBE", "XOM",
        "PYPL", "CSCO", "NFLX", "PFE", "KO", "PEP", "INTC", "CMCSA", "AVGO", "COST",
        "ABT", "TMO", "NEE", "DHR", "MCD", "NKE", "ACN", "TXN", "BMY", "PM",
        "PLTR", "AMD", "CRM", "ORCL", "QCOM", "INTU", "AMGN", "HON", "LOW", "UPS",
    ]
