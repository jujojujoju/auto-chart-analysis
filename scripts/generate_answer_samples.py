#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""정답 차트 샘플 JSON 생성.

실행: python scripts/generate_answer_samples.py
생성 위치: samples/
- 카카오, 네이버, 다올투자증권, CJ CGV, LG전자(066570.KS), HMM(011200.KS)
- 5년 일봉 + 기술적지표
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.data.market_data import fetch_ohlcv
from src.logic.ohlcv_processor import process_ohlcv_to_json

# 정답 차트: (yfinance symbol, 저장 파일명)
ANSWER_CHARTS = [
    ("035720.KS", "kakao"),           # 카카오
    ("035420.KS", "naver"),           # 네이버
    ("030210.KS", "daol"),            # 다올투자증권
    ("079160.KS", "cj_cgv"),          # CJ CGV
    ("066570.KS", "lg_electronics"),  # LG전자
    ("011200.KS", "hmm"),             # HMM
]

def main():
    samples_dir = PROJECT_ROOT / "samples"
    samples_dir.mkdir(parents=True, exist_ok=True)

    for symbol, name in ANSWER_CHARTS:
        try:
            df = fetch_ohlcv(symbol, period="5y")
            chart = process_ohlcv_to_json(df, symbol, add_indicators=True)
            out = samples_dir / f"answer_{name}.json"
            with open(out, "w", encoding="utf-8") as f:
                json.dump(chart, f, ensure_ascii=False, indent=2)
            print("OK:", symbol, "->", out.name)
        except Exception as e:
            print("SKIP:", symbol, e)

if __name__ == "__main__":
    main()
