"""WhatsApp — interface pronta (ex.: WhatsApp Cloud API ou Z-API). Não implementado na V1."""
from __future__ import annotations

import os

from radar.notifications.base import Notifier


class WhatsAppNotifier(Notifier):
    name = "whatsapp"

    @property
    def enabled(self) -> bool:
        return False  # habilitar quando WHATSAPP_* for implementado

    def send(self, title: str, text: str) -> bool:  # pragma: no cover
        raise NotImplementedError("Implementar com WHATSAPP_TOKEN / WHATSAPP_PHONE_ID: "
                                  f"{bool(os.getenv('WHATSAPP_TOKEN'))}")
