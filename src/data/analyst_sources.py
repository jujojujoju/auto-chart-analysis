# -*- coding: utf-8 -*-
"""해외·한국 애널리스트/펀드/RSS 분석 정보 수집.

- Founders Fund 포트폴리오
- Finviz, Seeking Alpha, Naver RSS → Gemini 필터 (추천·위험신호)
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class AnalystItem:
    """애널리스트 추천/위험 종목 정보."""
    name: str       # 종목명
    ticker: str     # 심볼 (005930.KS, PLTR 등)
    reason: str     # 근거
    source: str     # 출처


def fetch_all_analyst_items(
    api_key: Optional[str] = None,
    dart_api_key: Optional[str] = None,
) -> Tuple[List[AnalystItem], List[AnalystItem]]:
    """모든 애널리스트 소스에서 수집.
    Returns: (추천 종목 리스트, 위험신호 종목 리스트)
    """
    recommended: List[AnalystItem] = []
    warning: List[AnalystItem] = []
    recommended.extend(_fetch_founders_fund())
    recommended.extend(_fetch_dart(dart_api_key))
    recommended.extend(_fetch_privateshare_stub())
    if api_key:
        rec, warn = _fetch_rss_filtered(api_key)
        recommended.extend(rec)
        warning.extend(warn)
    return recommended, warning


def _fetch_founders_fund() -> List[AnalystItem]:
    """Founders Fund 포트폴리오 기반."""
    from .founders_fund import crawl_founders_fund_portfolio
    from .company_mapping import COMPANY_TO_TICKER

    items: List[AnalystItem] = []
    try:
        companies = crawl_founders_fund_portfolio()
    except Exception:
        return items

    for name in companies:
        ticker = COMPANY_TO_TICKER.get(name, "")
        if not ticker or not ticker.strip():
            continue
        sym = ticker if "." in ticker else ticker
        items.append(AnalystItem(
            name=name,
            ticker=sym,
            reason="Founders Fund 포트폴리오 편입",
            source="Founders Fund",
        ))
    return items


def _fetch_dart(api_key: Optional[str]) -> List[AnalystItem]:
    """DART 전자공시 - 최근 공시 종목."""
    if not api_key:
        return []
    from .dart_source import fetch_recent_disclosures

    items: List[AnalystItem] = []
    try:
        for d in fetch_recent_disclosures(api_key, days=3)[:15]:
            items.append(AnalystItem(
                name=d.corp_name,
                ticker=d.stock_code,
                reason=d.report_nm[:150],
                source="DART 공시",
            ))
    except Exception:
        pass
    return items


def _fetch_privateshare_stub() -> List[AnalystItem]:
    """프라이빗쉐어 펀드 (추후 연결)."""
    return []


def _fetch_rss_filtered(api_key: str) -> Tuple[List[AnalystItem], List[AnalystItem]]:
    """RSS 수집 후 Gemini로 필터링. (추천, 위험신호) 반환."""
    from .rss_sources import fetch_all_rss_items
    from ..intelligence.gemini_analyzer import filter_rss_with_gemini

    recommended: List[AnalystItem] = []
    warning: List[AnalystItem] = []
    try:
        rss_items = fetch_all_rss_items()
        if not rss_items:
            return recommended, warning
        texts = [f"[{r.source}] {r.title} | {r.summary[:200]}" for r in rss_items]
        result = filter_rss_with_gemini(texts, api_key)
        for x in result.get("recommended", []):
            ticker = x.get("ticker", "").strip()
            if ticker:
                recommended.append(AnalystItem(
                    name=x.get("name", ticker), ticker=ticker,
                    reason=x.get("reason", "")[:200], source=x.get("source", "RSS")[:50],
                ))
        for x in result.get("warning", []):
            ticker = x.get("ticker", "").strip()
            if ticker:
                warning.append(AnalystItem(
                    name=x.get("name", ticker), ticker=ticker,
                    reason=x.get("reason", "")[:200], source=x.get("source", "RSS")[:50],
                ))
    except Exception:
        pass
    return recommended, warning
