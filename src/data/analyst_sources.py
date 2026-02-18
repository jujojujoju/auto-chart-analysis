# -*- coding: utf-8 -*-
"""해외·한국 애널리스트/펀드 분석 정보 수집.

- Founders Fund 포트폴리오
- 확장 가능: 프라이빗쉐어 펀드, 애널리스트 사이트, 유튜버 등
"""

from dataclasses import dataclass
from typing import List


@dataclass
class AnalystItem:
    """애널리스트 추천 종목 정보."""
    name: str       # 종목명
    ticker: str     # 심볼 (005930.KS, PLTR 등)
    reason: str     # 근거
    source: str     # 출처 (Founders Fund, 유튜버 등)


def fetch_all_analyst_items() -> List[AnalystItem]:
    """모든 애널리스트 소스에서 수집."""
    items: List[AnalystItem] = []
    items.extend(_fetch_founders_fund())
    items.extend(_fetch_privateshare_stub())  # TODO: 실제 크롤링 연결
    return items


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
        # 미국주는 .붙이지 않음, 한국주는 .KS/.KQ
        sym = ticker if "." in ticker else ticker
        items.append(AnalystItem(
            name=name,
            ticker=sym,
            reason="Founders Fund 포트폴리오 편입",
            source="Founders Fund",
        ))
    return items


def _fetch_privateshare_stub() -> List[AnalystItem]:
    """프라이빗쉐어 펀드 (추후 실제 API/크롤링 연결)."""
    # TODO: 프라이빗쉐어 펀드 공개 포트폴리오가 있다면 크롤링
    return []
