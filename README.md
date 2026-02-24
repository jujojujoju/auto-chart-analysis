# AI 투자 비서 (Auto Chart Analysis)

미국·한국 시장을 대상으로 **종목 분석**과 **차트 분석**을 수행해, 각각 TOP 10을 선정하고 텔레그램으로 전송하는 파이프라인입니다.

---

## 시퀀스 및 동작 방식

### 전체 흐름

1. **유니버스**  
   - 미국: S&P 500 (Wikipedia, **캐시 미사용**·항상 재수집)  
   - 한국: 시가총액 순위 500종목 (FinanceDataReader KRX, **캐시 미사용**·항상 재수집)

2. **차트 데이터**  
   - 일봉 기준 **3년치** OHLCV 수집 (캐시 사용)  
   - 기술적 지표: **50·100·200 이평선**, 골든/데드 크로스, **정배열 여부**, **200 이평선 대비 이격도**, RSI

3. **1차 필터 (기계적)**  
   - 골든크로스 또는 50/100/200 정배열 + 이격도 적정(0.85~1.20) + 거래량 급증  
   - **후보 50개 이하**로 압축 (RPD 절약)

4. **종목 분석 (Gemini)**  
   - 후보에 대해 **미국**: Finviz(목표가·Recom·테이블)·Yahoo(현재가·OPM) / **한국**: Fnguide(영업이익·매출액·리포트) 수집  
   - 종목별 **3일 TTL 캐시** 사용(만료 시에만 재수집), OPM은 **영업이익/매출로 직접 계산**  
   - **배치**: 10종목씩 Gemini 호출, 호출 간 12초 대기  
   - 스코어: **괴리율 30% + 재무(OPM) 40% + 심리(리포트/헤드라인) 30%**  
   - **사용량 초과(429) 시**: gemini-2.5-flash → 2.5-flash-lite만 시도, 둘 다 실패하면 **Gemini 호출 중단** → 괴리·OPM 기준으로만 TOP 10 선정  
   - 미국 TOP 10, 한국 TOP 10 선정

5. **차트 분석**  
   - 50/100/200 정배열·골든크로스·200 이격도 적정·RSI 30 이하 등 규칙 점수 산출  
   - Gemini에 배치 전달해 정답 패턴 유사도 반영, **실패/429 시 규칙 기반만**으로 TOP 10 선정  
   - 미국 TOP 10, 한국 TOP 10 선정

6. **텔레그램 전송**  
   - 섹션: 1. 종목 분석 (한국 10 / 미국 10), 2. 차트 분석 (한국 10 / 미국 10)  
   - 각 항목에 **근거** 포함

---

## 데이터 출처

### 미국 (US)

| 용도 | 출처 | URL/방식 |
|------|------|----------|
| 종목 풀 | S&P 500 | Wikipedia `List of S&P 500 companies` (캐시 미사용) |
| OHLCV | yfinance | 일봉 3년, 캐시 사용 |
| 목표가·Recom | Finviz | `https://finviz.com/quote.ashx?t={TICKER}` (Target Price, Recommendation, 테이블) |
| 현재가·OPM | Yahoo Finance | yfinance (현재가, 재무제표에서 **영업이익/매출로 OPM 직접 계산**) |

### 한국 (KR)

| 용도 | 출처 | URL/방식 |
|------|------|----------|
| 종목 풀 | FinanceDataReader | `fdr.StockListing('KRX')` 시가총액 정렬 상위 500 |
| OHLCV | yfinance | 일봉 3년 (예: 005930.KS) |
| 재무·리포트 | Fnguide | `https://comp.fnguide.com/SVO2/ASP/SVD_Main.asp?gicode=A{6자리}` (영업이익·매출액으로 **OPM 직접 계산**, 목표가, 리팅 문구) |
| 공시 | Open DART | 현재 API 미연동으로 **주석 처리** (`opendart.fss.or.kr/api/fnlttSinglAcnt.json`) |

---

## API 사용 전략 (Gemini)

- **1차 필터**: 파이썬으로만 후보 **50개 이하** 축소  
- **배치**: 10종목씩 1회 호출, 호출 간 **12초 대기**  
- **모델**: gemini-2.5-flash → 2.5-flash-lite만 시도(각 1회). **둘 다 429면** Gemini 호출 중단 → 괴리·OPM(종목) / 규칙(차트) 기준으로만 TOP 10  
- **마지막 성공 모델**은 `cache/last_gemini_model.txt`에 저장되어 다음 실행부터 해당 모델만 사용

---

## 스코어 공식 (종목 분석)

- **괴리율 (Gap, 30%)**: `(목표가 - 현재가) / 현재가 × 100`  
- **재무 (Fundamental, 40%)**: OPM(영업이익/매출 직접 계산)  
- **심리 (Sentiment, 30%)**: 한국 Fnguide 리포트 등 가능한 데이터로 반영  

Gemini에 사전 계산값을 넘기고, 가중 합산·TOP 10 선정·근거 작성. **API 실패 시** 괴리·OPM만으로 폴백 점수 산출.

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
├── cache/               # OHLCV 캐시, stock_analysis_us/kr(종목별 3일 TTL), last_gemini_model.txt
├── output/              # daily_report.json
├── run_pipeline.py
├── .env
└── .github/workflows/    # 매일 09:00 KST 1회 실행 (workflow_dispatch로 수동 실행 가능)
```

---

## 기술 스택

- **데이터**: pandas, yfinance, FinanceDataReader (KR), urllib/requests
- **기술적 분석**: ta (SMA, RSI 등), 50/100/200 이평·골드크로스·이격도 자체 계산
- **AI**: Google Gemini (퀀트 전문가 시스템 프롬프트 + 배치 호출)
- **알림**: 텔레그램 Bot API
