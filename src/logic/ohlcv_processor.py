"""OHLCV를 JSON으로 가공하고 기술적 지표 추가."""

import json
from pathlib import Path
from typing import Any, Optional

import pandas as pd

try:
    from ta.trend import SMAIndicator, EMAIndicator
    from ta.momentum import RSIIndicator
    from ta.volatility import BollingerBands
    from ta.volume import OnBalanceVolumeIndicator
    HAS_TA = True
except ImportError:
    HAS_TA = False


def add_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """이평선, RSI, 볼린저밴드, OBV 등 기술적 지표 추가."""
    out = df.copy()

    if not HAS_TA:
        return out

    # 이평선
    for window in [5, 20, 60]:
        sma = SMAIndicator(close=df["Close"], window=window)
        out[f"sma_{window}"] = sma.sma_indicator()
        ema = EMAIndicator(close=df["Close"], window=window)
        out[f"ema_{window}"] = ema.ema_indicator()

    # RSI
    rsi = RSIIndicator(close=df["Close"], window=14)
    out["rsi"] = rsi.rsi()

    # 볼린저밴드
    bb = BollingerBands(close=df["Close"], window=20, window_dev=2)
    out["bb_upper"] = bb.bollinger_hband()
    out["bb_middle"] = bb.bollinger_mavg()
    out["bb_lower"] = bb.bollinger_lband()

    # OBV (거래량)
    obv = OnBalanceVolumeIndicator(close=df["Close"], volume=df["Volume"])
    out["obv"] = obv.on_balance_volume()

    return out


def process_ohlcv_to_json(
    df: pd.DataFrame,
    symbol: str,
    output_path: Optional[Path] = None,
    add_indicators: bool = True,
) -> dict[str, Any]:
    """OHLCV DataFrame을 JSON 포맷으로 변환.

    Args:
        df: OHLCV DataFrame
        symbol: 종목 심볼
        output_path: 저장할 파일 경로 (None이면 저장 안 함)
        add_indicators: 기술적 지표 포함 여부

    Returns:
        JSON 직렬화 가능한 dict
    """
    if add_indicators:
        df = add_technical_indicators(df)

    df = df.dropna(how="all", axis=1)
    df.index = df.index.astype(str)

    payload: dict[str, Any] = {
        "symbol": symbol,
        "period": f"{df.index[0]} ~ {df.index[-1]}",
        "rows": len(df),
        "ohlcv": df.to_dict(orient="index"),
        "columns": list(df.columns),
    }

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    return payload
