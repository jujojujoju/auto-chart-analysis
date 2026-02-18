"""chart_analyzer 모듈 테스트."""

import pytest
import pandas as pd
from src.chart_analyzer import load_ohlcv_from_csv, save_ohlcv


def test_save_and_load_ohlcv(tmp_path):
    """CSV 저장 후 로드 시 데이터 일치."""
    df = pd.DataFrame(
        {
            "Open": [100, 101],
            "High": [102, 103],
            "Low": [99, 100],
            "Close": [101, 102],
            "Volume": [1000, 1100],
        },
        index=pd.DatetimeIndex(["2024-01-01", "2024-01-02"]),
    )
    path = tmp_path / "test.csv"
    save_ohlcv(df, path)
    loaded = load_ohlcv_from_csv(path)
    pd.testing.assert_frame_equal(df, loaded)
