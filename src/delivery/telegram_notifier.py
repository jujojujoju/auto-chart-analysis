# -*- coding: utf-8 -*-
"""텔레그램 봇 푸시 알림."""

import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def send_telegram(
    message: str,
    bot_token: Optional[str],
    chat_id: Optional[str],
) -> bool:
    """텔레그램으로 메시지 전송."""
    if not bot_token or not chat_id:
        return False

    url = TELEGRAM_API.format(token=bot_token)
    payload = {
        "chat_id": chat_id,
        "text": message[:4096],
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    data = urllib.parse.urlencode(payload, encoding="utf-8").encode("utf-8")

    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded; charset=utf-8")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="ignore")
        except Exception:
            body = ""
        print("  [디버그] 텔레그램:", e.code, body[:200] if body else str(e))
        return False
    except Exception as e:
        print("  [디버그] 텔레그램 API 오류:", e)
        return False
