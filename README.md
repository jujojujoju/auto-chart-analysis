# AI 투자 비서 (Auto Chart Analysis)

미국·한국 시장을 대상으로 **종목 분석**과 **차트 분석**을 수행해, 각각 TOP 10을 선정하고 텔레그램으로 전송하는 파이프라인입니다.

---

## 시퀀스 및 동작 방식

### 전체 흐름

1. **유니버스**  
   - 미국: S&P 500 (Wikipedia 또는 yfinance) 500종목  
   - 한국: 시가총액 순위 500종목 (FinanceDataReader KRX)

2. **차트 데이터**  
   - 일봉 기준 **3년치** OHLCV 수집 (캐시 사용)  
   - 기술적 지표: **50·100·200 이평선**, 골든/데드 크로스, **정배열 여부**, **200 이평선 대비 이격도**, RSI

3. **1차 필터 (기계적)**  
   - 골든크로스 또는 50/100/200 정배열 + 이격도 적정(0.85~1.20) + 거래량 급증  
   - **후보 50개 이하**로 압축 (RPD 절약)

4. **종목 분석 (Gemini)**  
   - 후보에 대해 미국: Seeking Alpha·Finviz·Yahoo 재무 / 한국: Fnguide 수집  
   - **배치 전략**: 한 번에 10종목씩 묶어 API 호출, 호출 간 **12초 대기** (RPM 5 제한)  
   - 스코어: **목표가 괴리율 30% + 재무 건전성(OPM 등) 40% + 시장 심리 30%**  
   - 미국 TOP 10, 한국 TOP 10 선정

5. **차트 분석**  
   - 50/100/200 정배열·골든크로스·200 이격도 적정·정배열인데 RSI 30 이하 등으로 규칙 점수 산출  
   - 가능하면 Gemini에 배치로 전달해 정답 패턴 유사도 반영, 실패 시 **규칙 기반**만으로 TOP 10 선정  
   - 미국 TOP 10, 한국 TOP 10 선정

6. **텔레그램 전송**  
   - 섹션: 1. 종목 분석 (한국 10 / 미국 10), 2. 차트 분석 (한국 10 / 미국 10)  
   - 각 항목에 **근거** 포함

---

## 데이터 출처

### 미국 (US)

| 용도 | 출처 | URL/방식 |
|------|------|----------|
| 종목 풀 | S&P 500 | Wikipedia `List of S&P 500 companies` 또는 yfinance |
| OHLCV | yfinance | 일봉 3년 |
| 전문가 분석 | Seeking Alpha | `https://seekingalpha.com/symbol/{TICKER}/analysis` (상위 5개 헤드라인) |
| 전문가 분석 | Finviz | `https://finviz.com/quote.ashx?t={TICKER}` (Price Target, Rating 등 테이블 최대 20행) |
| 재무·기관 | Yahoo Finance | `https://finance.yahoo.com/quote/{TICKER}/financials` (OPM, 목표가 등) |

### 한국 (KR)

| 용도 | 출처 | URL/방식 |
|------|------|----------|
| 종목 풀 | FinanceDataReader | `fdr.StockListing('KRX')` 시가총액 정렬 상위 500 |
| OHLCV | yfinance | 일봉 3년 (예: 005930.KS) |
| 전문가·재무 | Fnguide | `https://comp.fnguide.com/SVO2/ASP/SVD_Main.asp?gicode=A{6자리}` (OPM, 목표가, 리팅 등) |
| 공시 | Open DART | 현재 API 미연동으로 **주석 처리** (`opendart.fss.or.kr/api/fnlttSinglAcnt.json`) |

---

## API 사용 전략 (RPD 20 / RPM 5)

- **1차 필터**: 파이썬으로만 수행해 AI에 넘길 후보를 **50개 이하**로 축소  
- **배치 크기**: 한 번에 **10종목**씩 묶어 1회 API 호출 → 50종목이면 **5회** RPD 사용  
- **RPM 제어**: 호출 사이 **12초 대기** (`time.sleep(12)`)

---

## 스코어 공식 (종목 분석)

- **목표가 괴리율 (Gap, 30%)**: `(목표가 - 현재가) / 현재가 × 100`. 괴리 20% 이상일 때 높은 점수  
- **재무 건전성 (Fundamental, 40%)**: 영업이익률(OPM) 10% 이상 또는 최근 분기 흑자 전환 시 가산  
- **시장 심리 (Sentiment, 30%)**: 리포트/헤드라인에 '역대급', 'Strong Buy', '상향' 등 긍정 단어 포함 시 가산  

가능한 데이터는 사전 계산해 Gemini에 넘기고, 모델은 가중 합산 및 TOP 10 선정·근거 작성에 사용합니다.

---

## 차트 분석 기준

- 50·100·200 이평선 **정배열**  
- **골든크로스** (50일선이 200일선 상향 돌파)  
- 200 이평선과의 **이격도**가 과도하게 벌어지지 않은 구간  
- 정배열인데 **RSI 30 이하** (과매도 구간) 우선  
- 정답 차트 패턴과의 유사도는 Gemini 호출 시 반영, **호출 실패 시 규칙만**으로 TOP 10 선정  

---

## 최종 텔레그램 포맷

```
📊 AI 투자 비서 리포트

━━━━━━━━━━━━━━━━━━━━
📌 1. 종목 분석
━━━━━━━━━━━━━━━━━━━━
🇰🇷 한국 TOP 10
  1. 종목명 (티커) | Score | 근거
  ...
🇺🇸 미국 TOP 10
  1. 종목명 (티커) | Score | 근거
  ...

━━━━━━━━━━━━━━━━━━━━
📈 2. 차트 분석
━━━━━━━━━━━━━━━━━━━━
🇰🇷 한국 TOP 10
  ...
🇺🇸 미국 TOP 10
  ...
```

---

## 필요한 API 키 / 설정

| 항목 | 필수 | 설명 |
|------|------|------|
| `GEMINI_API_KEY` | ✅ | [Google AI Studio](https://aistudio.google.com/) |
| `TELEGRAM_BOT_TOKEN` | ✅ | [@BotFather](https://t.me/botfather) `/newbot` |
| `TELEGRAM_CHAT_ID` | ✅ | [@userinfobot](https://t.me/userinfobot) 등으로 확인 |

`.env`에 위 값을 설정합니다.

---

## 설치 및 실행

```bash
cd auto-chart-analysis
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
# .env 생성 후 키 설정
python run_pipeline.py
```

---

## 폴더 구조

```
auto-chart-analysis/
├── config/              # 설정 (settings.py)
├── src/
│   ├── data/            # us_universe, kr_universe, us_sources, kr_sources, market_data
│   ├── logic/           # ohlcv_processor, indicators, filter_candidates
│   ├── intelligence/    # gemini_analyzer (배치 스코어링·차트 분석)
│   └── delivery/        # telegram_notifier
├── cache/               # OHLCV·정규화·유니버스 캐시
├── output/              # daily_report.json
├── run_pipeline.py
├── .env
└── .github/workflows/    # 스케줄 실행 (선택)
```

---

## 기술 스택

- **데이터**: pandas, yfinance, FinanceDataReader (KR), urllib/requests
- **기술적 분석**: ta (SMA, RSI 등), 50/100/200 이평·골드크로스·이격도 자체 계산
- **AI**: Google Gemini (퀀트 전문가 시스템 프롬프트 + 배치 호출)
- **알림**: 텔레그램 Bot API
