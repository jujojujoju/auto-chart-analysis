"""yfinance 기반 OHLCV 및 재무제표 수집. yfinance 실패 시 Alpha Vantage(선택) 대체."""

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from urllib.request import Request, urlopen

import pandas as pd
import yfinance as yf

# 캐시용: 일봉 최대 보관 기간 (일)
OHLCV_CACHE_MAX_DAYS = 365 * 3


def _normalize_symbol(symbol: str) -> str:
    """Yahoo 인식용: $ 제거, 공백 정리, BRK.B/BF.B 등 클래스주는 하이픈으로 (Yahoo는 BRK-B 사용)."""
    if not symbol or not isinstance(symbol, str):
        return symbol or ""
    s = symbol.strip().lstrip("$").strip()
    # Yahoo는 클래스 B/A 주를 하이픈으로 표기 (BRK-B, BF-B). 점이면 치환.
    if re.match(r"^[A-Z]{2,5}\.[AB]$", s, re.IGNORECASE):
        s = s.replace(".", "-", 1)
    return s


def _symbol_for_alpha_vantage(symbol: str) -> str:
    """Alpha Vantage용 심볼 (BRK-B → BRK.B, 한국주 .KS/.KQ 유지)."""
    s = _normalize_symbol(symbol)
    if "-" in s and len(s) <= 6:
        s = s.replace("-", ".")
    return s


def _fetch_ohlcv_alpha_vantage(
    symbol: str,
    start: datetime,
    end: datetime,
    api_key: Optional[str] = None,
) -> pd.DataFrame:
    """Alpha Vantage TIME_SERIES_DAILY로 OHLCV 수집. 키 없거나 실패 시 빈 DataFrame."""
    key = api_key or os.getenv("ALPHA_VANTAGE_API_KEY")
    if not key or not key.strip():
        return pd.DataFrame()
    sym = _symbol_for_alpha_vantage(symbol)
    url = (
        f"https://www.alphavantage.co/query?function=TIME_SERIES_DAILY"
        f"&symbol={sym}&apikey={key}&outputsize=full"
    )
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception:
        return pd.DataFrame()
    raw = data.get("Time Series (Daily)")
    if not raw or not isinstance(raw, dict):
        return pd.DataFrame()
    rows = []
    for date_str, v in raw.items():
        if not isinstance(v, dict):
            continue
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            if start and dt < start:
                continue
            if end and dt > end:
                continue
            rows.append({
                "date": dt,
                "Open": float(v.get("1. open", 0)),
                "High": float(v.get("2. high", 0)),
                "Low": float(v.get("3. low", 0)),
                "Close": float(v.get("4. close", 0)),
                "Volume": int(float(v.get("5. volume", 0))),
            })
        except (ValueError, TypeError):
            continue
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).set_index("date").sort_index()
    df.index = pd.DatetimeIndex(df.index)
    return df


def _ohlcv_cache_path(cache_dir: Path, symbol: str) -> Path:
    """종목별 OHLCV 캐시 파일 경로. symbol 내 '.' → '_' 치환."""
    safe = symbol.replace(".", "_")
    return (cache_dir / "ohlcv").resolve() / f"{safe}.csv"


def fetch_ohlcv_cached(
    symbol: str,
    cache_dir: Path,
    max_days: int = OHLCV_CACHE_MAX_DAYS,
    interval: str = "1d",
    prepost: bool = True,
) -> pd.DataFrame:
    """OHLCV를 캐시하고, 최신일 이후만 수집해 병합 후 캐시 갱신.

    - 캐시 없음: 3년치 수집 후 저장.
    - 캐시 있음: 마지막 날짜 다음부터 오늘까지만 수집해 기존과 병합, max_days 초과분 제거 후 저장.
    """
    symbol = _normalize_symbol(symbol)
    path = _ohlcv_cache_path(cache_dir, symbol)
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    end = now

    if path.exists():
        try:
            cached = pd.read_csv(path, index_col=0, parse_dates=True)
            if not cached.empty and isinstance(cached.index, pd.DatetimeIndex):
                cached.index = cached.index.tz_localize(None)
                last_date = cached.index.max()
                if last_date is not None:
                    # 최신일 다음날부터 수집. Yahoo는 '오늘' 일봉을 안 주는 경우가 있으므로 end = 오늘 0시(전일까지)로만 요청
                    start_new = last_date + timedelta(days=1)
                    end_for_fetch = end.replace(hour=0, minute=0, second=0, microsecond=0)
                    if start_new >= end_for_fetch:
                        # 요청 구간 없음(오늘만 남음) → Yahoo는 오늘 일봉을 안 주므로 캐시만 반환
                        cutoff = end - timedelta(days=max_days)
                        out = cached.loc[cached.index >= cutoff].copy()
                        if out.empty:
                            out = cached.tail(1)
                        return out.sort_index()
                    df_new = _fetch_ohlcv_range(symbol, start_new, end_for_fetch, interval=interval, prepost=prepost)
                    if df_new.empty:
                        cutoff = end - timedelta(days=max_days)
                        out = cached.loc[cached.index >= cutoff].copy().sort_index()
                        return out
                    combined = pd.concat([cached, df_new], axis=0)
                    combined = combined[~combined.index.duplicated(keep="last")]
                    combined = combined.sort_index()
                    cutoff = end - timedelta(days=max_days)
                    out = combined.loc[combined.index >= cutoff].copy()
                    out.to_csv(path, date_format="%Y-%m-%d")
                    return out
        except Exception:
            pass

    # 캐시 없음 또는 손상: 전체 기간 수집 (Yahoo가 오늘 일봉을 안 주므로 end = 오늘 0시로 요청)
    end_for_fetch = end.replace(hour=0, minute=0, second=0, microsecond=0)
    start = end_for_fetch - timedelta(days=max_days)
    df = _fetch_ohlcv_range(symbol, start, end_for_fetch, interval=interval, prepost=prepost)
    if df.empty and os.getenv("ALPHA_VANTAGE_API_KEY"):
        df = _fetch_ohlcv_alpha_vantage(symbol, start, end_for_fetch)
    if df.empty:
        raise ValueError(f"No OHLCV data for {symbol}")
    df.to_csv(path, date_format="%Y-%m-%d")
    return df


def _fetch_ohlcv_range(
    symbol: str,
    start: datetime,
    end: datetime,
    interval: str = "1d",
    prepost: bool = True,
) -> pd.DataFrame:
    """지정 구간 OHLCV 수집. 실패 시 period 재시도 → Alpha Vantage(키 있으면) 대체."""
    sym = _normalize_symbol(symbol)
    df = pd.DataFrame()
    try:
        ticker = yf.Ticker(sym)
        df = ticker.history(start=start, end=end, interval=interval, prepost=prepost, auto_adjust=True)
        if df.empty:
            try:
                df_per = ticker.history(period="5y", interval=interval, prepost=prepost, auto_adjust=True)
                if df_per is not None and not df_per.empty:
                    df_per.index = df_per.index.tz_localize(None) if df_per.index.tz is not None else df_per.index
                    df = df_per.loc[(df_per.index >= start) & (df_per.index <= end)]
            except Exception:
                pass
    except Exception:
        pass
    if df.empty and os.getenv("ALPHA_VANTAGE_API_KEY"):
        df = _fetch_ohlcv_alpha_vantage(symbol, start, end)
    if not df.empty and df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


def fetch_ohlcv(
    symbol: str,
    period: str = "3y",
    interval: str = "1d",
    prepost: bool = True,
) -> pd.DataFrame:
    """OHLCV 데이터 수집 (장외 거래 포함 옵션).

    Args:
        symbol: 심볼 (예: AAPL, 005930.KS). 앞의 $는 자동 제거.
        period: 기간 (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 3y, 5y). 3y=3년 제한
        interval: 봉 간격 (1d 권장)
        prepost: True면 장외 거래 포함

    Returns:
        Open, High, Low, Close, Volume 컬럼 DataFrame
    """
    sym = _normalize_symbol(symbol)
    ticker = yf.Ticker(sym)
    if period == "3y":
        end = datetime.now()
        start = end - timedelta(days=365 * 3)
        df = ticker.history(start=start, end=end, interval=interval, prepost=prepost, auto_adjust=True)
        if df.empty:
            df = ticker.history(period="5y", interval=interval, prepost=prepost, auto_adjust=True)
            if df is not None and not df.empty:
                df = df.loc[(df.index >= start) & (df.index <= end)]
        if df is None:
            df = pd.DataFrame()
    else:
        df = ticker.history(
            period=period,
            interval=interval,
            prepost=prepost,
            auto_adjust=True,
        )
    if df is None or df.empty:
        raise ValueError(f"No OHLCV data for {symbol}")
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


def fetch_financials(symbol: str) -> dict[str, Any]:
    """재무제표 수집 (yfinance 제공 시).

    Returns:
        financials, balance_sheet, cashflow DataFrame을 dict로
    """
    ticker = yf.Ticker(_normalize_symbol(symbol))
    result: dict[str, Any] = {}

    if ticker.financials is not None and not ticker.financials.empty:
        result["financials"] = ticker.financials.to_dict()
    if ticker.balance_sheet is not None and not ticker.balance_sheet.empty:
        result["balance_sheet"] = ticker.balance_sheet.to_dict()
    if ticker.cashflow is not None and not ticker.cashflow.empty:
        result["cashflow"] = ticker.cashflow.to_dict()

    return result


def summarize_financials_for_prompt(raw: dict[str, Any]) -> dict[str, Any]:
    """재무제표 raw dict를 Gemini 프롬프트용 요약으로 변환.

    yfinance to_dict() 구조: {날짜: {항목명: 값}} → 최신 연도 기준 핵심 지표만 추출
    """
    summary: dict[str, Any] = {}
    key_items = {
        "financials": ["Total Revenue", "Net Income", "Operating Income"],
        "balance_sheet": ["Total Assets", "Total Liabilities Net Minority Interest", "Total Debt", "Cash And Cash Equivalents"],
        "cashflow": ["Operating Cash Flow", "Free Cash Flow", "Capital Expenditure"],
    }

    for sheet, keys in key_items.items():
        data = raw.get(sheet, {})
        if not data:
            continue
        # 최신 연도 데이터 (날짜가 키)
        try:
            latest_date = sorted(data.keys(), reverse=True)[0]
        except TypeError:
            continue
        year_data = data.get(latest_date, {})
        if not isinstance(year_data, dict):
            continue
        summary[sheet] = {}
        for item in keys:
            if item in year_data:
                summary[sheet][item] = year_data[item]

    return summary
