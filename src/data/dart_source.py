# -*- coding: utf-8 -*-
"""DART Open API - 전자공시 데이터.

인증키: opendart.fss.or.kr 회원가입 후 발급.
.env에 DART_API_KEY 설정.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List
from urllib.request import Request, urlopen
from urllib.parse import urlencode
import json

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


@dataclass
class DartDisclosure:
    """DART 공시 항목."""
    corp_name: str
    report_nm: str
    rcept_dt: str
    stock_code: str


def _to_ticker(stock_code: str) -> str:
    """6자리 종목코드 → yfinance 티커."""
    if not stock_code or len(str(stock_code).strip()) < 5:
        return ""
    s = str(stock_code).strip().zfill(6)
    if s.startswith(("1", "2", "3", "4", "5", "6", "7", "8", "9")):
        return s + ".KQ"
    return s + ".KS"


def fetch_recent_disclosures(api_key: str, days: int = 3) -> List[DartDisclosure]:
    """최근 N일간 공시 목록 수집. corp_code 없이 전체 조회 (기간 3개월 제한)."""
    if not api_key or not api_key.strip():
        return []

    items: List[DartDisclosure] = []
    end = datetime.now()
    bgn = end - timedelta(days=days)
    bgn_str = bgn.strftime("%Y%m%d")
    end_str = end.strftime("%Y%m%d")

    try:
        url = (
            "https://opendart.fss.or.kr/api/list.json?"
            + urlencode({
                "crtfc_key": api_key,
                "bgn_de": bgn_str,
                "end_de": end_str,
                "page_no": 1,
                "page_count": 50,
            })
        )
        req = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("status") != "000":
            return []
        for row in data.get("list", []):
            stock = row.get("stock_code", "").strip()
            if not stock:
                continue
            items.append(DartDisclosure(
                corp_name=row.get("corp_name", ""),
                report_nm=row.get("report_nm", ""),
                rcept_dt=row.get("rcept_dt", ""),
                stock_code=_to_ticker(stock),
            ))
    except Exception:
        pass
    return items[:30]
