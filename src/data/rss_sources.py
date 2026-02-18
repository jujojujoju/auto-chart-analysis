# -*- coding: utf-8 -*-
"""RSS 기반 애널리스트/뉴스 수집.

- Finviz: 업그레이드/다운그레이드, 뉴스
- Seeking Alpha: Stock Ideas
- Naver: 경제 뉴스
"""

from dataclasses import dataclass
from typing import List
from urllib.request import Request, urlopen
from urllib.error import URLError

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


@dataclass
class RssItem:
    """RSS 항목."""
    title: str
    summary: str
    link: str
    source: str


def fetch_finviz_news() -> List[RssItem]:
    """Finviz 뉴스 RSS."""
    url = "https://finviz.com/rss/news.ashx"
    return _parse_rss(url, "Finviz")


def fetch_seeking_alpha() -> List[RssItem]:
    """Seeking Alpha Stock Ideas RSS."""
    url = "https://seekingalpha.com/stock-ideas.xml"
    return _parse_rss(url, "Seeking Alpha")


def fetch_naver_economy() -> List[RssItem]:
    """네이버 경제 뉴스 RSS."""
    url = "https://news.naver.com/main/rss/rss.naver?sid1=101"
    return _parse_rss(url, "Naver Economy")


def fetch_kiwoom_research() -> List[RssItem]:
    """키움증권 리서치 게시판 (크롤링)."""
    try:
        from .kiwoom_research import crawl_kiwoom_research
        items: List[RssItem] = []
        for k in crawl_kiwoom_research():
            items.append(RssItem(
                title=k.title,
                summary="",
                link=k.link,
                source="키움증권 리서치",
            ))
        return items
    except Exception:
        return []


def _parse_rss(url: str, source: str) -> List[RssItem]:
    """feedparser 또는 fallback으로 RSS 파싱."""
    try:
        import feedparser
    except ImportError:
        return _parse_rss_fallback(url, source)

    try:
        req = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        feed = feedparser.parse(raw)
        items = []
        for e in feed.entries[:50]:
            title = (e.get("title") or "").strip()
            summary = (e.get("summary", "") or e.get("description", "") or "").strip()
            link = (e.get("link") or "").strip()
            if title:
                items.append(RssItem(title=title, summary=summary[:500], link=link, source=source))
        return items
    except Exception:
        return []


def _parse_rss_fallback(url: str, source: str) -> List[RssItem]:
    """feedparser 없을 때 간단 RSS 2.0 파싱."""
    import xml.etree.ElementTree as ET

    items = []
    try:
        req = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        root = ET.fromstring(raw)
        for item in root.findall(".//item"):
            t = item.find("title")
            l = item.find("link")
            d = item.find("description")
            title = (t.text or "").strip() if t is not None else ""
            link = (l.text or "").strip() if l is not None else ""
            summary = (d.text or "").strip()[:500] if d is not None else ""
            if title:
                items.append(RssItem(title=title, summary=summary, link=link, source=source))
        return items[:50]
    except Exception:
        return []


def fetch_all_rss_items() -> List[RssItem]:
    """모든 RSS 소스에서 수집."""
    items: List[RssItem] = []
    items.extend(fetch_finviz_news())
    items.extend(fetch_seeking_alpha())
    items.extend(fetch_naver_economy())
    items.extend(fetch_kiwoom_research())
    return items
