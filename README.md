# AI 투자 비서 (Auto Chart Analysis)

매일 주기적으로 판단하는 AI 투자 비서 알림 서비스.

## 핵심 가치

- **감정 배제**: 기계적 기술 분석
- **초개인화**: 10개 정답 샘플 기반 In-Context Learning

## 아키텍처

```
Data Layer    → Founders Fund 크롤링, yfinance OHLCV/재무제표, (유튜브)
Logic Layer   → OHLCV JSON 가공 + 기술적 지표 (이평선, RSI, 볼린저, OBV)
Intelligence  → Gemini 2.0 Flash API로 10개 샘플과 비교 분석
Delivery      → GitHub Actions 매일 실행 + 텔레그램 푸시
```

## 필요한 API 키 / 키값

| 항목 | 필수 | 발급처 |
|------|------|--------|
| `GEMINI_API_KEY` | ✅ | [Google AI Studio](https://aistudio.google.com/) |
| `TELEGRAM_BOT_TOKEN` | ✅ | 텔레그램 [@BotFather](https://t.me/botfather) `/newbot` |
| `TELEGRAM_CHAT_ID` | ✅ | [@userinfobot](https://t.me/userinfobot) 에서 확인 |
| `YOUTUBE_API_KEY` | 선택 | [Google Cloud Console](https://console.cloud.google.com/apis/credentials) |

## 설치 및 설정

```bash
cd auto-chart-analysis
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
```

1. `.env.example`을 복사해 `.env` 생성
2. `.env`에 위 키값 입력

## 사용법

### 로컬 실행

```bash
python run_pipeline.py
```

### GitHub Actions (자동/수동 실행)

1. 저장소 `Settings → Secrets and variables → Actions` 에서 다음 시크릿 등록:
   - `GEMINI_API_KEY` (필수)
   - `TELEGRAM_BOT_TOKEN` (필수)
   - `TELEGRAM_CHAT_ID` (필수)
   - `YOUTUBE_API_KEY` (선택)
2. `Actions` 탭에서 워크플로 수동 실행 또는 스케줄 실행  
   - 테스트: 10분마다 (`*/10 * * * *`)  
   - 운영: 매일 00:00 UTC (`0 0 * * *`)로 변경 시 `daily-report.yml`의 cron 수정

## 10개 정답 샘플

`samples/` 폴더에 선호하는 차트 패턴 JSON을 넣으면 Gemini가 이 패턴을 기준으로 분석합니다.

```bash
# 샘플 생성 예시
python -c "
from src.data.market_data import fetch_ohlcv
from src.logic.ohlcv_processor import process_ohlcv_to_json
import json
df = fetch_ohlcv('AAPL', period='3mo')
d = process_ohlcv_to_json(df, 'AAPL')
with open('samples/AAPL_sample.json', 'w') as f:
    json.dump(d, f, indent=2)
"
```

## 폴더 구조

```
auto-chart-analysis/
├── config/           # 설정 (settings.py)
├── src/
│   ├── data/         # Founders Fund, yfinance, 재무제표
│   ├── logic/        # OHLCV JSON + 기술적 지표
│   ├── intelligence/ # Gemini 분석
│   └── delivery/     # 텔레그램
├── samples/          # 10개 정답 샘플 JSON
├── output/           # 일일 리포트 결과
├── run_pipeline.py
├── .env.example
└── .github/workflows/daily-report.yml
```

## 기술 스택

- **데이터**: pandas, yfinance, requests
- **기술적 분석**: ta (SMA, EMA, RSI, 볼린저, OBV)
- **AI**: Google Gemini 2.0 Flash
- **알림**: 텔레그램 Bot API
