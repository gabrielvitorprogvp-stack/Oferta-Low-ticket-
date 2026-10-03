"""Email (SMTP) — interface pronta. Ative definindo SMTP_HOST, SMTP_USER, SMTP_PASS, ALERT_EMAIL_TO."""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage

from radar.notifications.base import Notifier


class EmailNotifier(Notifier):
    name = "email"

    def __init__(self):
        self.host = os.getenv("SMTP_HOST", "")
        self.port = int(os.getenv("SMTP_PORT", "587"))
        self.user = os.getenv("SMTP_USER", "")
        self.password = os.getenv("SMTP_PASS", "")
        self.to = os.getenv("ALERT_EMAIL_TO", "")

    @property
    def enabled(self) -> bool:
        return bool(self.host and self.to)

    def send(self, title: str, text: str) -> bool:
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = title, self.user or self.to, self.to
        msg.set_content(text)
        with smtplib.SMTP(self.host, self.port, timeout=20) as s:
            s.starttls()
            if self.user:
                s.login(self.user, self.password)
            s.send_message(msg)
        return True
