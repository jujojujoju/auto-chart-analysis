# -*- coding: utf-8 -*-
"""한국 시장 데이터: Fnguide. (DART API 연동 안 됨 시 주석 처리)

- Fnguide: https://comp.fnguide.com/SVO2/ASP/SVD_Main.asp?gertxt=1&pGB=1&c3=&gicode=A{TICKER}
  티커 005930.KS → gicode=A005930 (A + 6자리)
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
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
    # 추가 지표 (스코어 수치화용)
    per: Optional[float] = None
    pbr: Optional[float] = None
    roe_pct: Optional[float] = None
    eps: Optional[float] = None
    debt_ratio_pct: Optional[float] = None
    div_yield_pct: Optional[float] = None
    # 실적이슈·시세현황·컨센서스·운용사보유·Business Summary
    actual_op_income_100m: Optional[float] = None  # 확정실적 영업이익 억원
    expected_op_yoy_pct: Optional[float] = None   # 예상실적 전년대비 %
    yoy_pct: Optional[float] = None                # 전년동기대비 %
    market_cap_100m: Optional[float] = None
    foreign_pct: Optional[float] = None
    beta: Optional[float] = None
    return_1m_pct: Optional[float] = None
    return_3m_pct: Optional[float] = None
    return_1y_pct: Optional[float] = None
    business_summary: Optional[str] = None
    consensus_line: Optional[str] = None            # "투자의견 Buy 4.0, 목표주가 229,800원"
    institutional_holdings: List[Dict[str, Any]] = field(default_factory=list)  # [{"name":"삼성자산운용","shares_1000":68811}, ...]


def _parse_number_after_label(html: str, labels: list, max_chars: int = 200) -> Optional[float]:
    """라벨 다음에 나오는 첫 숫자(쉼표/소수 포함) 추출."""
    for label in labels:
        idx = html.find(label)
        if idx == -1:
            continue
        block = html[idx : idx + max_chars]
        m = re.search(r"([-]?[\d,]+(?:\.\d+)?)\s*%?", block)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                pass
    return None


def _clean_text(s: str) -> str:
    """HTML 조각·태그 제거. '<' or '>' 포함 시 빈 문자열."""
    if not s or "<" in s or ">" in s:
        return ""
    return s.strip()[:500]


def fetch_fnguide_main(gicode: str) -> dict:
    """Fnguide SVD_Main 페이지에서 재무·목표가·실적이슈·시세현황·운용사보유·Business Summary 등 추출."""
    url = f"https://comp.fnguide.com/SVO2/ASP/SVD_Main.asp?gertxt=1&pGB=1&c3=&gicode={gicode}"
    out = {
        "opm": None, "target_price": None, "rating": None, "texts": [],
        "per": None, "pbr": None, "roe_pct": None, "eps": None, "debt_ratio_pct": None, "div_yield_pct": None,
        "actual_op_income_100m": None, "expected_op_yoy_pct": None, "yoy_pct": None,
        "market_cap_100m": None, "foreign_pct": None, "beta": None,
        "return_1m_pct": None, "return_3m_pct": None, "return_1y_pct": None,
        "business_summary": None, "consensus_line": None, "institutional_holdings": [],
    }
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
        # ----- 목표주가: Fnguide 전용 (미국은 us_sources에서 Finviz/Yahoo로 별도 처리) -----
        # 1) thead/th 구조: 목표주가</th> 다음 데이터 행(tr)에서 두 번째 td 값 (한샘 49,375 등)
        if out["target_price"] is None:
            m = re.search(r"목표주가\s*</th>.*?</tr>\s*.*?<tr[^>]*>.*?<td[^>]*>[^<]*</td>\s*<td[^>]*>([\d,]+)</td>", html, re.DOTALL | re.IGNORECASE)
            if m:
                try:
                    v = float(m.group(1).replace(",", ""))
                    if 1000 < v < 100000000:
                        out["target_price"] = v
                except ValueError:
                    pass
        # 2) 기존: 목표주가 라벨 뒤 인접 셀 숫자
        for m in re.finditer(r"목표주가[^<]*</[^>]+>\s*<[^>]+>[^<]*?([\d,]+(?:\.\d+)?)", html):
            try:
                out["target_price"] = float(m.group(1).replace(",", ""))
                break
            except ValueError:
                pass
        if out["target_price"] is None:
            for m in re.finditer(r"목표가[^<]*</[^>]+>\s*<[^>]+>[^<]*?([\d,]+(?:\.\d+)?)", html):
                try:
                    out["target_price"] = float(m.group(1).replace(",", ""))
                    break
                except ValueError:
                    pass
        if out["target_price"] is None:
            for m in re.finditer(r"Target\s*Price[^<]*</[^>]+>\s*<[^>]+>[^<]*?([\d,]+(?:\.\d+)?)", html, re.I):
                try:
                    out["target_price"] = float(m.group(1).replace(",", ""))
                    break
                except ValueError:
                    pass
        # 목표 주가 (공백 포함) 또는 td 내 숫자만 있는 셀 패턴
        if out["target_price"] is None:
            for m in re.finditer(r"목표\s*주가[^<]*</[^>]+>\s*<[^>]+>[^<]*?([\d,]+(?:\.\d+)?)", html):
                try:
                    out["target_price"] = float(m.group(1).replace(",", ""))
                    break
                except ValueError:
                    pass
        if out["target_price"] is None:
            for m in re.finditer(r"목표주가[^<]*<[^>]+>[^<]*?([\d,]{4,})", html):
                try:
                    v = float(m.group(1).replace(",", ""))
                    if 1000 < v < 10000000:
                        out["target_price"] = v
                        break
                except ValueError:
                    pass
        # 목표주가 테이블/섹션 내에서 쉼표 포함 큰 금액(목표가 후보) 추출 — 컨센서스 행 구조와 무관
        if out["target_price"] is None:
            for m in re.finditer(r"목표주가\s*</t[dh]>.*?([\d]{1,3}(?:,[\d]{3}){2,})", html, re.DOTALL | re.IGNORECASE):
                try:
                    v = float(m.group(1).replace(",", ""))
                    if 10000 < v < 100000000:  # 1만~1억 원 구간
                        out["target_price"] = v
                        break
                except ValueError:
                    pass
        if out["target_price"] is None:
            for m in re.finditer(r"목표주가[^<]*(?:<[^>]+>[^<]*)*?([\d]{6,8})\s*</td>", html):
                try:
                    v = float(m.group(1))
                    if 100000 < v < 100000000:
                        out["target_price"] = v
                        break
                except ValueError:
                    pass
        # PER: [PER](javascript... 또는 PER(배) 뒤 숫자
        out["per"] = _parse_number_after_label(html, ["[PER](javascript", "PER(배)", "PER(Price Earning"])
        if out["per"] is None:
            for m in re.finditer(r"PER[^0-9]{0,30}([\d,]+(?:\.\d+)?)\s*(?:배|12M|업종)?", html):
                try:
                    v = float(m.group(1).replace(",", ""))
                    if 0.1 < v < 10000:
                        out["per"] = v
                        break
                except ValueError:
                    pass
        # PBR
        out["pbr"] = _parse_number_after_label(html, ["[PBR](javascript", "PBR(Price Book", "PBR(배)"])
        if out["pbr"] is None:
            for m in re.finditer(r"PBR[^0-9]{0,30}([\d,]+(?:\.\d+)?)\s*", html):
                try:
                    v = float(m.group(1).replace(",", ""))
                    if 0.01 < v < 1000:
                        out["pbr"] = v
                        break
                except ValueError:
                    pass
        # ROE(%)
        out["roe_pct"] = _parse_number_after_label(html, ["ROE(%)(지배", "[ROE](javascript", "ROE(%"])
        if out["roe_pct"] is None:
            for m in re.finditer(r"ROE[^0-9]{0,20}([\d,]+(?:\.\d+)?)\s*%", html):
                try:
                    out["roe_pct"] = float(m.group(1).replace(",", ""))
                    break
                except ValueError:
                    pass
        # EPS(원)
        out["eps"] = _parse_number_after_label(html, ["EPS(원)", "EPS(주당순이익)"])
        if out["eps"] is None:
            for m in re.finditer(r"EPS[^0-9]{0,20}([\d,]+(?:\.\d+)?)\s*(?:원)?", html):
                try:
                    v = float(m.group(1).replace(",", ""))
                    if 0 < v < 1e10:
                        out["eps"] = v
                        break
                except ValueError:
                    pass
        # 부채비율(%)
        out["debt_ratio_pct"] = _parse_number_after_label(html, ["부채비율(%)(총부채", "부채비율(%"])
        # 배당수익률
        out["div_yield_pct"] = _parse_number_after_label(html, ["배당수익률](javascript", "배당수익률"])

        # 실적이슈: 확정실적(영업이익 억원), 3개월전예상대비(%), 전년동기대비(%)
        perf = re.search(r"실적이슈.*?확정실적\(영업이익[^)]*\).*?<td[^>]*>([\d,]+)</td>\s*<td[^>]*>([-+]?[\d,]+(?:\.\d+)?)\s*%?\s*</td>\s*<td[^>]*>([-+]?[\d,]+(?:\.\d+)?)\s*%?", html, re.DOTALL | re.IGNORECASE)
        if perf:
            try:
                out["actual_op_income_100m"] = float(perf.group(1).replace(",", ""))
                out["expected_op_yoy_pct"] = float(perf.group(2).replace(",", ""))
                out["yoy_pct"] = float(perf.group(3).replace(",", ""))
            except (ValueError, IndexError):
                pass
        if out["yoy_pct"] is None:
            perf2 = re.search(r"실적이슈.*?([\d,]+)\s*[|\s]*([-+]?[\d,]+(?:\.\d+)?)\s*[|\s]*([-+]?[\d,]+(?:\.\d+)?)", html, re.DOTALL)
            if perf2:
                try:
                    out["actual_op_income_100m"] = float(perf2.group(1).replace(",", ""))
                    out["expected_op_yoy_pct"] = float(perf2.group(2).replace(",", ""))
                    out["yoy_pct"] = float(perf2.group(3).replace(",", ""))
                except (ValueError, IndexError):
                    pass
        if out["yoy_pct"] is None:
            for m in re.finditer(r"전년동기대비\s*[^0-9]*([-+]?[\d,]+(?:\.\d+)?)\s*%", html):
                try:
                    out["yoy_pct"] = float(m.group(1).replace(",", ""))
                    break
                except ValueError:
                    pass

        # 시세현황: 종가/전일대비, 거래량, 52주고저, 수익률 1M/3M/1Y, 외국인지분율, 시가총액, 베타
        for m in re.finditer(r"시세현황.*?([\d,]+)/\s*([+-]?[\d,]+)/\s*([+-]?[\d.]+)\s*%\s*[|\s]*([\d,]+)", html, re.DOTALL):
            try:
                out["market_cap_100m"] = float(m.group(1).replace(",", ""))  # 종가 등
                break
            except (ValueError, IndexError):
                pass
        out["market_cap_100m"] = _parse_number_after_label(html, ["시가총액](javascript:void(0))(상장예정포함,억원)", "시가총액(보통주,억원)"]) or out["market_cap_100m"]
        out["foreign_pct"] = _parse_number_after_label(html, ["외국인 지분율", "외국인지분율"])
        out["beta"] = _parse_number_after_label(html, ["베타(1년)", "베타"])
        for m in re.finditer(r"수익률\(1M/\s*3M/\s*6M/\s*1Y\)[^0-9]*([+-]?[\d.]+)\s*/\s*([+-]?[\d.]+)\s*/\s*[^|]*\s*/\s*([+-]?[\d.]+)", html):
            try:
                out["return_1m_pct"] = float(m.group(1))
                out["return_3m_pct"] = float(m.group(2))
                out["return_1y_pct"] = float(m.group(3))
                break
            except (ValueError, IndexError):
                pass

        # 투자의견 컨센서스: thead/tbody 허용, 헤더 다음 데이터 행에서 (투자의견, 목표주가) 추출
        consensus_row = re.search(r"투자의견\s*</t[dh]>.*?목표주가\s*</t[dh]>.*?</tr>\s*.*?<tr[^>]*>.*?<td[^>]*>([\d.]+)</td>\s*<td[^>]*>([\d,]+)</td>", html, re.DOTALL | re.IGNORECASE)
        if not consensus_row:
            consensus_row = re.search(r"목표주가\s*</t[dh]>.*?</tr>\s*.*?<tr[^>]*>.*?<td[^>]*>([\d.]+)</td>\s*<td[^>]*>([\d,]+)</td>", html, re.DOTALL | re.IGNORECASE)
        if consensus_row:
            try:
                opinion_val = float(consensus_row.group(1))
                tp_val = float(consensus_row.group(2).replace(",", ""))
                if 1 <= opinion_val <= 5:
                    label = "S/Buy" if opinion_val >= 4.5 else "Buy" if opinion_val >= 4 else "Hold" if opinion_val >= 3 else "U/Weight" if opinion_val >= 2 else "Sell"
                    out["consensus_line"] = "투자의견 %s %.1f" % (label, opinion_val)
                if tp_val > 0:
                    if out["target_price"] is None:
                        out["target_price"] = tp_val
                    if out["consensus_line"]:
                        out["consensus_line"] += ", 목표주가 %s원" % (str(int(tp_val)))
                    else:
                        out["consensus_line"] = "목표주가 %s원" % (str(int(tp_val)))
            except (ValueError, IndexError, TypeError):
                pass
        if not out["consensus_line"] and out["target_price"]:
            out["consensus_line"] = "목표주가 %s원" % (str(int(out["target_price"])))

        # 운용사별 보유 현황: (운용사명, 보유수량) 테이블 행
        inst_block = re.search(r"운용사별\s*보유\s*현황.*?</table>", html, re.DOTALL | re.IGNORECASE)
        if inst_block:
            bl = inst_block.group(0)
            # td 셀에서 숫자(보유수량)와 그 앞 td(운용사명) 매칭. 또는 연속 td 두 개 (이름, 수량)
            for m in re.finditer(r"<td[^>]*>([^<]+)</td>\s*<td[^>]*>([\d,]+(?:\.\d+)?)\s*</td>", bl):
                name_cell = m.group(1).strip()
                num_cell = m.group(2).replace(",", "")
                if "<" in name_cell or ">" in name_cell or not name_cell:
                    continue
                if re.match(r"^[\d.]+$", name_cell):
                    continue
                try:
                    shares = float(num_cell)
                    if shares > 0 and shares < 1e10:
                        out["institutional_holdings"].append({"name": name_cell[:50], "shares_1000": round(shares, 2)})
                except ValueError:
                    pass
            if not out["institutional_holdings"]:
                for m in re.finditer(r">([가-힣a-zA-Z\s]+자산운용|한국투자신탁운용|엔에이치아문디자산운용|교보악사자산운용|키움투자자산운용|신한자산운용|한화자산운용|한국투자밸류자산운용)<", bl):
                    name = m.group(1).strip()
                    if name and name not in [x.get("name") for x in out["institutional_holdings"]]:
                        out["institutional_holdings"].append({"name": name, "shares_1000": None})
                for i, m in enumerate(re.finditer(r"<td[^>]*>\s*([\d,]+(?:\.\d+)?)\s*</td>", bl)):
                    try:
                        val = float(m.group(1).replace(",", ""))
                        if 100 < val < 1e8 and i < 20:
                            idx = min(i, len(out["institutional_holdings"]) - 1)
                            if idx >= 0 and out["institutional_holdings"][idx].get("shares_1000") is None:
                                out["institutional_holdings"][idx]["shares_1000"] = round(val, 2)
                    except (ValueError, IndexError):
                        pass

        # Business Summary: "Business Summary" 다음 본문(리스트/문단)
        bs = re.search(r"Business\s*Summary\s*</[^>]+>.*?(?:<[^>]+>)([^<]{50,800})", html, re.DOTALL | re.I)
        if bs:
            raw_bs = re.sub(r"\s+", " ", bs.group(1)).strip()
            out["business_summary"] = _clean_text(raw_bs[:600]) or None

        # headlines/reports: 컨센서스 한 줄 + Business Summary 요약만 (보유수량 제외)
        if out["consensus_line"]:
            t = _clean_text(out["consensus_line"])
            if t and t not in out["texts"]:
                out["texts"].append(t)
        if out["business_summary"]:
            t = "Business Summary: " + (out["business_summary"][:200].strip() + "…" if len(out["business_summary"]) > 200 else out["business_summary"])
            if _clean_text(t) and t not in out["texts"]:
                out["texts"].append(t[:300])
        out["texts"] = [x for x in out["texts"] if _clean_text(x)]
        if out["texts"]:
            out["rating"] = out["texts"][0][:80]
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
    data.headlines_or_reports = (raw.get("texts") or [])[:15]
    data.per = raw.get("per")
    data.pbr = raw.get("pbr")
    data.roe_pct = raw.get("roe_pct")
    data.eps = raw.get("eps")
    data.debt_ratio_pct = raw.get("debt_ratio_pct")
    data.div_yield_pct = raw.get("div_yield_pct")
    data.actual_op_income_100m = raw.get("actual_op_income_100m")
    data.expected_op_yoy_pct = raw.get("expected_op_yoy_pct")
    data.yoy_pct = raw.get("yoy_pct")
    data.market_cap_100m = raw.get("market_cap_100m")
    data.foreign_pct = raw.get("foreign_pct")
    data.beta = raw.get("beta")
    data.return_1m_pct = raw.get("return_1m_pct")
    data.return_3m_pct = raw.get("return_3m_pct")
    data.return_1y_pct = raw.get("return_1y_pct")
    data.business_summary = raw.get("business_summary")
    data.consensus_line = raw.get("consensus_line")
    data.institutional_holdings = raw.get("institutional_holdings") or []
    return data


# DART API 연동 (현재 미연동으로 주석 처리)
# def fetch_dart_fnltt(corp_code: str, api_key: str) -> Optional[dict]:
#     """opendart.fss.or.kr/api/fnlttSinglAcnt.json 연동."""
#     return None
