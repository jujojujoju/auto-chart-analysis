"""Founders Fund 포트폴리오 웹사이트 크롤링."""

import re
from urllib.request import Request, urlopen
from urllib.error import URLError

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
PORTFOLIO_URL = "https://foundersfund.com/portfolio/"


def crawl_founders_fund_portfolio() -> list[str]:
    """Founders Fund 포트폴리오 페이지에서 회사명 리스트 수집.

    Returns:
        회사명 리스트 (예: ["SpaceX", "Palantir", ...])
    """
    req = Request(PORTFOLIO_URL, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except URLError as e:
        raise RuntimeError(f"Founders Fund 크롤링 실패: {e}") from e

    # h2 태그 내 회사명 패턴 (페이지 구조에 맞게 조정)
    # 예: <h2>SpaceX</h2>, <h2 class="...">Palantir</h2>
    pattern = re.compile(r'<h2[^>]*>([^<]+)</h2>', re.IGNORECASE)
    matches = pattern.findall(html)

    # Portfolio, Founders Fund 등 제목 제외, 회사명만
    exclude = {"portfolio", "founders fund", "about", "contact"}
    companies = [
        m.strip()
        for m in matches
        if m.strip() and m.strip().lower() not in exclude
    ]

    return list(dict.fromkeys(companies))  # 순서 유지하며 중복 제거
