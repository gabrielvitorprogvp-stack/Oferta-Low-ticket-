from __future__ import annotations

import logging

import httpx

from radar.config import get_settings
from radar.notifications.base import Notifier

log = logging.getLogger("radar.telegram")


class TelegramNotifier(Notifier):
    name = "telegram"

    def __init__(self):
        s = get_settings()
        self.token, self.chat_id = s.telegram_bot_token, s.telegram_chat_id

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, title: str, text: str) -> bool:
        msg = text if text.startswith(title) else f"{title}\n\n{text}"
        for attempt in range(3):
            try:
                r = httpx.post(f"https://api.telegram.org/bot{self.token}/sendMessage",
                               json={"chat_id": self.chat_id, "text": msg[:4000],
                                     "disable_web_page_preview": True}, timeout=20)
                if r.status_code == 200:
                    return True
                log.warning("telegram status %s: %s", r.status_code, r.text[:200])
                if r.status_code < 500 and r.status_code != 429:
                    return False
            except httpx.HTTPError as e:
                log.warning("telegram erro: %s", e)
        return False
