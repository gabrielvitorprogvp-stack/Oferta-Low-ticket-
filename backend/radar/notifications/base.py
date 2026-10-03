"""Arquitetura de notificações: cada canal implementa Notifier. Telegram já funciona;
WhatsApp/email têm a interface pronta para implementação."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

log = logging.getLogger("radar.notify")


class Notifier(ABC):
    name: str = "base"

    @property
    @abstractmethod
    def enabled(self) -> bool: ...

    @abstractmethod
    def send(self, title: str, text: str) -> bool: ...


def get_notifiers() -> list[Notifier]:
    from radar.notifications.email import EmailNotifier
    from radar.notifications.telegram import TelegramNotifier
    from radar.notifications.whatsapp import WhatsAppNotifier
    return [n for n in (TelegramNotifier(), WhatsAppNotifier(), EmailNotifier()) if n.enabled]


def broadcast(title: str, text: str) -> list[str]:
    sent = []
    for n in get_notifiers():
        try:
            if n.send(title, text):
                sent.append(n.name)
        except Exception as e:  # noqa: BLE001 — notificação nunca derruba a rodada
            log.error("falha ao notificar via %s: %s", n.name, e)
    return sent
