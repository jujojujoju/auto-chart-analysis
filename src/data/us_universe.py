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
CACHE_FILENAME = "sp500_tickers.json"


def fetch_sp500_tickers_with_cache(cache_dir: Path) -> List[str]:
    """S&P 500 종목 리스트. 캐시 있으면 재사용 (같은 날)."""
    today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
    cache_path = cache_dir / CACHE_FILENAME

    if cache_path.exists():
        try:
            with open(cache_path, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("date") == today:
                return data.get("tickers", [])
        except (json.JSONDecodeError, OSError):
            pass

    tickers = _fetch_sp500_from_wikipedia()
    if tickers:
        cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump({"date": today, "tickers": tickers}, f, indent=2)
        except OSError:
            pass

    return tickers


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
    return tickers[:600] if tickers else _fallback_sp500()


def _fallback_sp500() -> List[str]:
    """네트워크 실패 시 기본 종목 리스트."""
    return [
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B", "JPM", "V",
        "JNJ", "WMT", "PG", "MA", "UNH", "HD", "DIS", "BAC", "ADBE", "XOM",
        "PYPL", "CSCO", "NFLX", "PFE", "KO", "PEP", "INTC", "CMCSA", "AVGO", "COST",
        "ABT", "TMO", "NEE", "DHR", "MCD", "NKE", "ACN", "TXN", "BMY", "PM",
        "PLTR", "AMD", "CRM", "ORCL", "QCOM", "INTU", "AMGN", "HON", "LOW", "UPS",
    ]
