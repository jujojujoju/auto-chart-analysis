# -*- coding: utf-8 -*-
"""미국 시장 데이터: Finviz(목표가·Recom·테이블) + Yahoo Finance.

- Finviz: https://finviz.com/quote.ashx?t={TICKER} (Target Price, Recommendation, 메인·애널리스트 테이블)
- Yahoo: https://finance.yahoo.com (현재가·재무·OPM)
"""

import re
from dataclasses import dataclass, field
from typing import Any, List, Optional
from urllib.request import Request, urlopen

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


@dataclass
class USStockData:
    ticker: str
    current_price: float = 0.0
    volume_change_pct: Optional[float] = None
    finviz_targets: List[dict] = field(default_factory=list)  # Target Price, Recommendation, Price Target Change 테이블 등
    opm_pct: Optional[float] = None
    institutional_pct: Optional[float] = None
    target_price: Optional[float] = None
    rating: Optional[str] = None
    finviz_url: Optional[str] = None
    # 추가 지표 (스코어 수치화용)
    per: Optional[float] = None
    pbr: Optional[float] = None
    roe_pct: Optional[float] = None
    eps: Optional[float] = None
    div_yield_pct: Optional[float] = None


def fetch_finviz_quote(ticker: str, max_rows: int = 20) -> List[dict]:
    """Finviz quote 페이지에서 Price Target Change, Rating 등 테이블 추출."""
    url = f"https://finviz.com/quote.ashx?t={ticker.upper()}"
    rows: List[dict] = []
    try:
        req = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=12) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        # 테이블 행: td 내 숫자·등급 등
        table = re.search(r"Price Target Change</td>.*?</table>", html, re.DOTALL)
        if table:
            block = table.group(0)
            for m in re.finditer(r"<td[^>]*>([^<]+)</td>\s*<td[^>]*>([^<]*)</td>", block):
                k, v = m.group(1).strip(), m.group(2).strip()
                if k and v:
                    rows.append({"key": k[:80], "value": v[:80]})
                    if len(rows) >= max_rows:
                        break
        # 목표가: Target Price 등
        for m in re.finditer(r"Target Price</td>\s*<td[^>]*>([^<]+)</td>", html):
            rows.append({"key": "Target Price", "value": m.group(1).strip()[:40]})
            break
        for m in re.finditer(r"Recommendation</td>\s*<td[^>]*>([^<]+)</td>", html):
            rows.append({"key": "Recommendation", "value": m.group(1).strip()[:40]})
            break
    except Exception:
        pass
    return rows[:max_rows]


def fetch_yahoo_financials_opm(ticker: str) -> Optional[float]:
    """Yahoo Finance 재무제표에서 영업이익·매출을 가져와 OPM = 영업이익/매출*100 으로 직접 계산."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        fin = t.financials
        if fin is None or fin.empty:
            return None
        rev = fin.loc["Total Revenue"].iloc[0] if "Total Revenue" in fin.index else (fin.loc["Operating Revenue"].iloc[0] if "Operating Revenue" in fin.index else None)
        op_income = fin.loc["Operating Income"].iloc[0] if "Operating Income" in fin.index else None
        if rev is not None and op_income is not None and float(rev) != 0:
            return round(float(op_income) / float(rev) * 100, 2)
    except Exception:
        pass
    return None


def _safe_float(val: Any, default: Optional[float] = None) -> Optional[float]:
    if val is None:
        return default
    try:
        v = float(val)
        return v if (v == v and abs(v) < 1e15) else default  # NaN/inf 제외
    except (TypeError, ValueError):
        return default


def fetch_us_stock_data(ticker: str) -> USStockData:
    """한 종목에 대해 Finviz(목표가·Recom·테이블), Yahoo(현재가·OPM·PER·PBR·ROE 등) 수집."""
    data = USStockData(ticker=ticker)
    data.finviz_url = f"https://finviz.com/quote.ashx?t={ticker.upper()}"
    data.finviz_targets = fetch_finviz_quote(ticker, 20)
    data.opm_pct = fetch_yahoo_financials_opm(ticker)
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        info = t.info
        data.current_price = float(info.get("currentPrice") or info.get("regularMarketPrice") or 0)
        data.target_price = info.get("targetMeanPrice") or info.get("targetHighPrice")
        if data.target_price is not None:
            data.target_price = float(data.target_price)
        if not data.target_price and data.finviz_targets:
            for row in data.finviz_targets:
                if row.get("key", "").strip() == "Target Price":
                    try:
                        v = row.get("value", "").replace(",", "").replace("$", "")
                        data.target_price = float(v)
                        break
                    except ValueError:
                        pass
        # PER, PBR, ROE, EPS, 배당수익률 (스코어 수치화용)
        data.per = _safe_float(info.get("trailingPE") or info.get("forwardPE"))
        data.pbr = _safe_float(info.get("priceToBook"))
        roe = info.get("returnOnEquity")
        if roe is not None:
            data.roe_pct = _safe_float(roe * 100 if abs(roe) <= 1 else roe)
        data.eps = _safe_float(info.get("trailingEps") or info.get("forwardEps"))
        div = info.get("dividendYield")
        if div is not None:
            data.div_yield_pct = _safe_float(div * 100 if abs(div) <= 1 else div)
    except Exception:
        pass
    return data
