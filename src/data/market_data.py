"""yfinance 기반 OHLCV 및 재무제표 수집."""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf

# 캐시용: 일봉 최대 보관 기간 (일)
OHLCV_CACHE_MAX_DAYS = 365 * 3


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
                    # 최신일 다음날부터 오늘까지만 수집 (공휴일/주말은 yfinance가 비워줌)
                    start_new = last_date + timedelta(days=1)
                    if start_new >= end:
                        # 이미 최신이면 재계산 없이 캐시만 잘라서 반환
                        cutoff = end - timedelta(days=max_days)
                        out = cached.loc[cached.index >= cutoff].copy()
                        if out.empty:
                            out = cached.tail(1)
                        return out.sort_index()
                    df_new = _fetch_ohlcv_range(symbol, start_new, end, interval=interval, prepost=prepost)
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

    # 캐시 없음 또는 손상: 전체 기간 수집
    start = end - timedelta(days=max_days)
    df = _fetch_ohlcv_range(symbol, start, end, interval=interval, prepost=prepost)
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
    """지정 구간 OHLCV 수집."""
    ticker = yf.Ticker(symbol)
    df = ticker.history(start=start, end=end, interval=interval, prepost=prepost, auto_adjust=True)
    if df.empty:
        return df
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
        symbol: 심볼 (예: AAPL, 005930.KS)
        period: 기간 (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 3y, 5y). 3y=3년 제한
        interval: 봉 간격 (1d 권장)
        prepost: True면 장외 거래 포함

    Returns:
        Open, High, Low, Close, Volume 컬럼 DataFrame
    """
    ticker = yf.Ticker(symbol)
    # 3y는 yfinance 미지원 → start/end로 3년 요청
    if period == "3y":
        end = datetime.now()
        start = end - timedelta(days=365 * 3)
        df = ticker.history(start=start, end=end, interval=interval, prepost=prepost, auto_adjust=True)
    else:
        df = ticker.history(
            period=period,
            interval=interval,
            prepost=prepost,
            auto_adjust=True,
        )
    if df.empty:
        raise ValueError(f"No OHLCV data for {symbol}")
    return df


def fetch_financials(symbol: str) -> dict[str, Any]:
    """재무제표 수집 (yfinance 제공 시).

    Returns:
        financials, balance_sheet, cashflow DataFrame을 dict로
    """
    ticker = yf.Ticker(symbol)
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
