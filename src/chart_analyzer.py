"""차트 데이터 로드 및 기본 시각화."""

from pathlib import Path
from typing import Union

try:
    import pandas as pd
    import yfinance as yf
except ImportError as e:
    raise ImportError("pip install pandas yfinance") from e


def load_ohlcv(
    symbol: str,
    period: str = "1mo",
    interval: str = "1d",
) -> "pd.DataFrame":
    """yfinance로 OHLCV 데이터 로드.

    Args:
        symbol: 심볼 (예: '005930.KS', 'AAPL')
        period: 기간 (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y)
        interval: 봉 간격 (1m, 2m, 5m, 15m, 30m, 1h, 1d, 1wk)

    Returns:
        DataFrame with columns Open, High, Low, Close, Volume
    """
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period, interval=interval)
    if df.empty:
        raise ValueError(f"No data for symbol: {symbol}")
    return df


def save_ohlcv(df: "pd.DataFrame", filepath: Union[str, Path]) -> None:
    """OHLCV를 CSV로 저장."""
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(filepath)


def load_ohlcv_from_csv(filepath: Union[str, Path]) -> "pd.DataFrame":
    """CSV에서 OHLCV 로드 (index를 DatetimeIndex로 복원)."""
    df = pd.read_csv(filepath, index_col=0, parse_dates=True)
    return df


def plot_chart(
    df: "pd.DataFrame",
    title: str = "Chart",
    figsize: tuple = (12, 6),
) -> None:
    """종가 라인 차트 그리기 (matplotlib)."""
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=figsize)
    ax.plot(df.index, df["Close"], label="Close")
    ax.set_title(title)
    ax.set_xlabel("Date")
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.show()
