# -*- coding: utf-8 -*-
"""텔레그램 설정 테스트. 실행: python test_telegram.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

import os
from src.delivery.telegram_notifier import send_telegram

token = os.getenv("TELEGRAM_BOT_TOKEN")
chat_id = os.getenv("TELEGRAM_CHAT_ID")

print("TELEGRAM_BOT_TOKEN:", (token[:10] + "...") if token else "(없음)")
print("TELEGRAM_CHAT_ID:", chat_id or "(없음)")

if token and chat_id:
    ok = send_telegram("테스트 메시지 from AI 투자 비서", token, chat_id)
    print("전송 결과:", "성공" if ok else "실패")
else:
    print(".env에 TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID를 확인하세요.")
