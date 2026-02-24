# -*- coding: utf-8 -*-
"""한국 시장 데이터: Fnguide. (DART API 연동 안 됨 시 주석 처리)

- Fnguide: https://comp.fnguide.com/SVO2/ASP/SVD_Main.asp?gertxt=1&pGB=1&c3=&gicode=A{TICKER}
  티커 005930.KS → gicode=A005930 (A + 6자리)
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.request import Request, urlopen

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def kr_ticker_to_gicode(ticker: str) -> str:
    """005930.KS -> A005930"""
    code = (ticker or "").split(".")[0].replace(" ", "").zfill(6)
    return "A" + code


@dataclass
class KRStockData:
    ticker: str
    current_price: float = 0.0
    volume_change_pct: Optional[float] = None
    opm_pct: Optional[float] = None
    target_price: Optional[float] = None
    rating: Optional[str] = None
    headlines_or_reports: List[str] = field(default_factory=list)
    fnguide_url: Optional[str] = None


def fetch_fnguide_main(gicode: str) -> dict:
    """Fnguide SVD_Main 페이지에서 재무·목표가·리포트 추출. OPM은 영업이익/매출액으로 직접 계산."""
    url = f"https://comp.fnguide.com/SVO2/ASP/SVD_Main.asp?gertxt=1&pGB=1&c3=&gicode={gicode}"
    out = {"opm": None, "target_price": None, "rating": None, "texts": []}
    try:
        req = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=12) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        # 영업이익·매출액 파싱 후 OPM = 영업이익/매출액*100 직접 계산
        revenue: Optional[float] = None
        op_income: Optional[float] = None
        # 매출액: 매출액 라벨 뒤 숫자 (단위 억/만 등 제거용으로 숫자만)
        for m in re.finditer(r"매출액[^<]*</[^>]+>\s*<[^>]+>[^<]*?([-]?[\d,]+(?:\.\d+)?)", html):
            try:
                revenue = float(m.group(1).replace(",", ""))
                if revenue != 0:
                    break
            except ValueError:
                pass
        if revenue is None:
            for m in re.finditer(r"Revenue[^<]*</[^>]+>\s*<[^>]+>[^<]*?([-]?[\d,]+(?:\.\d+)?)", html, re.I):
                try:
                    revenue = float(m.group(1).replace(",", ""))
                    if revenue != 0:
                        break
                except ValueError:
                    pass
        # 영업이익
        for m in re.finditer(r"영업이익[^<]*</[^>]+>\s*<[^>]+>[^<]*?([-]?[\d,]+(?:\.\d+)?)", html):
            try:
                op_income = float(m.group(1).replace(",", ""))
                break
            except ValueError:
                pass
        if op_income is None:
            for m in re.finditer(r"Operating\s*Income[^<]*</[^>]+>\s*<[^>]+>[^<]*?([-]?[\d,]+(?:\.\d+)?)", html, re.I):
                try:
                    op_income = float(m.group(1).replace(",", ""))
                    break
                except ValueError:
                    pass
        if revenue is not None and op_income is not None and revenue != 0:
            out["opm"] = round(op_income / revenue * 100, 2)
        # 목표가
        for m in re.finditer(r"목표가[^<]*</[^>]+>\s*<[^>]+>([\d,]+)", html):
            try:
                out["target_price"] = float(m.group(1).replace(",", ""))
                break
            except ValueError:
                pass
        # 리포트/의견 문구
        for m in re.finditer(r">(매수|매도|중립|상향|하향|Strong Buy|Buy|Hold|보유|적정가)[^<]{0,50}</", html):
            t = m.group(0).strip("><").strip()
            if t and t not in out["texts"]:
                out["texts"].append(t[:100])
        if out["texts"]:
            out["rating"] = out["texts"][0][:50]
    except Exception:
        pass
    return out


def fetch_kr_stock_data(ticker: str, current_price: float = 0.0) -> KRStockData:
    """한 종목 Fnguide 수집. current_price는 차트에서 넣어줄 수 있음."""
    data = KRStockData(ticker=ticker, current_price=current_price)
    gicode = kr_ticker_to_gicode(ticker)
    data.fnguide_url = f"https://comp.fnguide.com/SVO2/ASP/SVD_Main.asp?gertxt=1&pGB=1&c3=&gicode={gicode}"
    raw = fetch_fnguide_main(gicode)
    data.opm_pct = raw.get("opm")
    data.target_price = raw.get("target_price")
    data.rating = raw.get("rating")
    data.headlines_or_reports = (raw.get("texts") or [])[:10]
    return data


# DART API 연동 (현재 미연동으로 주석 처리)
# def fetch_dart_fnltt(corp_code: str, api_key: str) -> Optional[dict]:
#     """opendart.fss.or.kr/api/fnlttSinglAcnt.json 연동."""
#     return None
