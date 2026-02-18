# -*- coding: utf-8 -*-
"""유튜브 채널에서 추천 종목 수집 (캐싱 적용).

YouTube Data API v3 사용.
API 키가 없으면 건너뜀.
같은 날 중복 요청 방지: cache/youtube_tickers_YYYY-MM-DD.json
"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, List, Optional

# 경제사냥꾼 채널 ID
CHANNEL_ECONOMY_HUNTER = "UC7usMJDHmtbs_oegmzQKKMA"

# 영상 제목/설명에서 추출할 미국주식 티커 패턴 (2~5 대문자)
US_TICKER_PATTERN = re.compile(r"\b([A-Z]{2,5})\b")
# 한국주식 6자리 종목코드
KR_TICKER_PATTERN = re.compile(r"\b(\d{6})\b")


def _extract_tickers_from_text(text: str) -> List[str]:
    """텍스트에서 티커 추출."""
    tickers = set()
    # 미국주식
    for m in US_TICKER_PATTERN.finditer(text.upper()):
        t = m.group(1)
        if t not in ("API", "CEO", "ETF", "IPO", "AI", "IT", "USA"):
            tickers.add(t)
    # 한국주식 (6자리 → yfinance 형식 005930.KS)
    for m in KR_TICKER_PATTERN.finditer(text):
        tickers.add(m.group(1) + ".KS")
    return list(tickers)


def fetch_youtube_tickers_with_cache(
    api_key: Optional[str],
    cache_dir: Path,
) -> List[str]:
    """경제사냥꾼 채널 최근 24시간 영상에서 종목 추출. 캐시 있으면 재사용."""
    if not api_key:
        return []

    today = datetime.now().strftime("%Y-%m-%d")
    cache_path = cache_dir / f"youtube_tickers_{today}.json"

    # 캐시 hit
    if cache_path.exists():
        try:
            with open(cache_path, encoding="utf-8") as f:
                data = json.load(f)
                return data.get("tickers", [])
        except (json.JSONDecodeError, OSError):
            pass

    # API 호출
    tickers = _fetch_from_youtube_api(api_key)
    tickers = list(dict.fromkeys(tickers))  # 중복 제거, 순서 유지

    # 캐시 저장
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"date": today, "tickers": tickers}, f, ensure_ascii=False, indent=2)
    except OSError:
        pass

    return tickers


def _fetch_from_youtube_api(api_key: str) -> List[str]:
    """YouTube API로 경제사냥꾼 채널 최근 24시간 영상에서 종목 추출."""
    try:
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
    except ImportError:
        return []

    published_after = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    all_tickers = []

    try:
        youtube = build("youtube", "v3", developerKey=api_key)
        request = youtube.search().list(
            part="snippet",
            channelId=CHANNEL_ECONOMY_HUNTER,
            type="video",
            order="date",
            publishedAfter=published_after,
            maxResults=15,
        )
        response = request.execute()

        for item in response.get("items", []):
            snippet = item.get("snippet", {})
            title = snippet.get("title", "")
            desc = snippet.get("description", "")
            text = f"{title} {desc}"
            all_tickers.extend(_extract_tickers_from_text(text))

    except (HttpError, Exception):
        return []

    return all_tickers
