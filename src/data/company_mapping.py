"""Founders Fund 포트폴리오 회사명 → 공개주식 심볼 매핑."""

# 공개 거래 회사만 (미공개는 수집 대상 아님)
COMPANY_TO_TICKER: dict[str, str] = {
    "Palantir": "PLTR",
    "Stripe": "",  # 미상장
    "Facebook": "META",
    "Airbnb": "ABNB",
    "Affirm": "AFRM",
    "Spotify": "SPOT",
    "Twilio": "TWLO",
    "Credit Karma": "",  # Intuit 인수
    "Figma": "",  # Adobe 인수 무산
    "Asana": "ASAN",
    "Lyft": "LYFT",
    "Wish": "WISH",
    "The Athletic": "",  # NYT 인수
    "Flexport": "",  # 비상장
    "Faire": "",  # 비상장
    "Oscar": "OSCR",
    "Kavak": "",  # 비상장
    "Rippling": "",  # 비상장
    "Ramp": "",  # 비상장
    "OpenAI": "",  # 비상장
    "SpaceX": "",  # 비상장
    "Neuralink": "",  # 비상장
    "Anduril": "",  # 비상장
    "Boring Company": "",  # 비상장
    "DeepMind": "",  # Google 자회사
    "PsiQuantum": "",  # 비상장
    "Scale": "",  # 비상장
    "Nubank": "NU",
    "Trade Republic": "",  # 비상장
    "Polymarket": "",  # 비상장
    "Crusoe": "",  # 비상장
}


def get_public_tickers(company_names: list) -> list:
    """회사명 리스트에서 공개 주식 심볼만 추출."""
    tickers = []
    seen = set()
    for name in company_names:
        ticker = COMPANY_TO_TICKER.get(name)
        if ticker and ticker.strip() and ticker not in seen:
            tickers.append(ticker)
            seen.add(ticker)
    return tickers
