"""환경 변수 및 설정 로드."""

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# 프로젝트 루트 기준 .env 로드
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def get_env(key: str, default: Optional[str] = None) -> Optional[str]:
    """환경 변수 조회."""
    return os.getenv(key, default)


# 필수
GEMINI_API_KEY = get_env("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = get_env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = get_env("TELEGRAM_CHAT_ID")

# 선택 (없으면 해당 수집기 스킵)
YOUTUBE_API_KEY = get_env("YOUTUBE_API_KEY")
DART_API_KEY = get_env("DART_API_KEY")  # opendart.fss.or.kr 인증키
# yfinance 실패 시 차트 데이터 대체 소스 (무료 키: https://www.alphavantage.co/support/#api-key)
ALPHA_VANTAGE_API_KEY = get_env("ALPHA_VANTAGE_API_KEY")

# 차트 패턴: True면 Gemini 대신 규칙 기반 매처만 사용 (API 비용/효율)
USE_RULE_BASED_PATTERN = (get_env("USE_RULE_BASED_PATTERN", "").lower() in ("1", "true", "yes"))

# 경로
DATA_DIR = PROJECT_ROOT / "data"
SAMPLE_DIR = PROJECT_ROOT / "samples"  # 10개 정답 샘플
OUTPUT_DIR = PROJECT_ROOT / "output"
CACHE_DIR = PROJECT_ROOT / "cache"
