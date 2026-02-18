# -*- coding: utf-8 -*-
"""매수세(거래량) 상위 종목 추출."""

from typing import List, Tuple


def get_top_by_buying_pressure(
    charts: list[dict],
    ticker_names: dict[str, str],
    n: int = 10,
    days: int = 5,
) -> List[Tuple[str, str]]:
    """최근 N일 거래량 합계 기준 상위 종목. (ticker, name) 리스트."""
    scores = []
    for ch in charts:
        sym = ch.get("symbol", "")
        if not sym:
            continue
        ohlcv = ch.get("ohlcv", {})
        if not ohlcv:
            continue
        items = list(ohlcv.items())[-days:]
        total_vol = 0
        buy_vol = 0  # 상승일 거래량 (Close > Open)
        for _, row in items:
            if isinstance(row, dict):
                v = row.get("Volume") or 0
                try:
                    total_vol += float(v)
                except (TypeError, ValueError):
                    pass
                try:
                    if float(row.get("Close", 0)) > float(row.get("Open", 0)):
                        buy_vol += float(v)
                except (TypeError, ValueError):
                    pass
        # 매수세 = 상승일 거래량 비중 * 총거래량 (또는 단순 총거래량)
        score = buy_vol if buy_vol > 0 else total_vol
        name = ticker_names.get(sym, sym)
        scores.append((sym, name, score))
    scores.sort(key=lambda x: x[2], reverse=True)
    return [(s, n) for s, n, _ in scores[:n]]
