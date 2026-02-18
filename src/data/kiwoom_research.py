# -*- coding: utf-8 -*-
"""키움증권 리서치 리포트 크롤링.

리서치 게시판에서 제목·종목 언급 수집.
"""

from dataclasses import dataclass
from typing import List
from urllib.request import Request, urlopen
import re

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

RESEARCH_URL = "https://www.kiwoom.com/h/invest/research/VMarketIMView"


@dataclass
class KiwoomResearchItem:
    """키움 리서치 항목."""
    title: str
    link: str
    date: str


def crawl_kiwoom_research() -> List[KiwoomResearchItem]:
    """키움증권 리서치 게시판 크롤링. (동적 페이지면 빈 리스트 반환 가능)"""
    items: List[KiwoomResearchItem] = []
    try:
        req = Request(RESEARCH_URL, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        # 정적 HTML에서 제목·링크 추출 시도
        # 패턴: 게시글 제목, 링크 등 (실제 구조에 맞게 조정 필요)
        for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>([^<]{10,100})</a>', html, re.DOTALL):
            href, text = m.group(1), re.sub(r"\s+", " ", m.group(2).strip())
            if "research" in href.lower() or "리포트" in text or "추천" in text or "종목" in text:
                items.append(KiwoomResearchItem(title=text[:200], link=href, date=""))
        items = items[:20]
    except Exception:
        pass
    return items
