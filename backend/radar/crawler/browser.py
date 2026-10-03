"""Navegador persistente (Playwright, API síncrona).

- Perfil persistente em data/browser_profile: cookies/sessão sobrevivem entre rodadas, e o
  usuário pode logar manualmente com `python -m radar login`.
- Detecta bloqueios (login wall, checkpoint, CAPTCHA, "tráfego incomum"). Nunca tenta
  resolver CAPTCHA: sinaliza BLOCKED e o pipeline pausa a fonte e pede intervenção.
"""
from __future__ import annotations

import logging
import random
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import BrowserContext, Error as PWError, Page, sync_playwright

from radar.config import get_settings

log = logging.getLogger("radar.browser")

BLOCK_URL_MARKERS = ("/checkpoint", "/login", "/sorry/", "captcha", "challenge", "/recaptcha")
BLOCK_TEXT_MARKERS = (
    "nossos sistemas detectaram tráfego incomum", "our systems have detected unusual traffic",
    "confirme que você não é um robô", "confirm you're not a robot", "verify you are human",
    "você foi bloqueado temporariamente", "you've been blocked", "you’re temporarily blocked",
    "faça login para continuar", "log in to continue", "precisamos confirmar que é você",
)


class BlockedError(RuntimeError):
    """A plataforma exigiu login/CAPTCHA/verificação: requer intervenção humana."""


class BrowserManager:
    def __init__(self, headless: bool | None = None):
        self.s = get_settings()
        self.headless = self.s.browser_headless if headless is None else headless
        self._pw = None
        self.ctx: BrowserContext | None = None
        self._last_nav: dict[str, float] = {}

    # ---------- ciclo de vida ----------
    def start(self) -> "BrowserManager":
        if self.ctx:
            return self
        self._pw = sync_playwright().start()
        kwargs = dict(
            user_data_dir=str(self.s.browser_profile_dir),
            headless=self.headless,
            locale=self.s.browser_locale,
            timezone_id=self.s.browser_timezone,
            viewport={"width": 1366, "height": 900},
            ignore_https_errors=self.s.browser_ignore_https_errors,
            args=["--disable-blink-features=AutomationControlled"],
        )
        exe = self.s.browser_executable_path
        if exe and Path(exe).exists():
            kwargs["executable_path"] = exe
        try:
            self.ctx = self._pw.chromium.launch_persistent_context(**kwargs)
        except PWError:
            # Playwright sem o build de Chromium esperado: tenta o binário do sistema
            fallback = "/opt/pw-browsers/chromium"
            if "executable_path" not in kwargs and Path(fallback).exists():
                kwargs["executable_path"] = fallback
                self.ctx = self._pw.chromium.launch_persistent_context(**kwargs)
            else:
                raise
        self.ctx.set_default_timeout(45000)
        return self

    def close(self) -> None:
        try:
            if self.ctx:
                self.ctx.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:  # noqa: BLE001
            pass
        self.ctx, self._pw = None, None

    def reopen(self) -> None:
        log.warning("reabrindo navegador")
        self.close()
        time.sleep(2)
        self.start()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.close()

    # ---------- utilitários ----------
    def new_page(self) -> Page:
        assert self.ctx, "browser não iniciado"
        return self.ctx.new_page()

    def throttle(self, key: str, min_delay: float) -> None:
        """Intervalo mínimo (com jitter) entre navegações para a mesma fonte."""
        last = self._last_nav.get(key)
        wait = 0.0
        if last is not None:
            wait = min_delay + random.uniform(0, min_delay * 0.5) - (time.time() - last)
        if wait > 0:
            time.sleep(wait)
        self._last_nav[key] = time.time()

    @staticmethod
    def check_blocked(page: Page, extra_text: str | None = None) -> str | None:
        path = urlparse((page.url or "").lower()).path  # só o caminho: queries podem citar "login"
        for m in BLOCK_URL_MARKERS:
            if m in path:
                return f"url de bloqueio: {m}"
        try:
            text = (extra_text if extra_text is not None else page.inner_text("body", timeout=5000))
        except PWError:
            text = ""
        low = (text or "").lower()[:5000]
        for m in BLOCK_TEXT_MARKERS:
            if m in low:
                return f"texto de bloqueio: {m}"
        return None

    def screenshot(self, page: Page, name: str) -> str | None:
        path = self.s.screenshots_dir / f"{name}.jpg"
        try:
            page.screenshot(path=str(path), full_page=True, type="jpeg", quality=60, timeout=20000)
            return path.name
        except PWError:
            try:
                page.screenshot(path=str(path), type="jpeg", quality=60)
                return path.name
            except PWError:
                return None


def interactive_login(url: str = "https://www.facebook.com/ads/library/") -> None:
    """Abre o navegador visível com o perfil persistente para login/verificação manual."""
    bm = BrowserManager(headless=False).start()
    page = bm.new_page()
    page.goto(url)
    print("Navegador aberto com o perfil persistente do Radar.\n"
          "Faça login / resolva a verificação manualmente e depois feche a janela "
          "(ou pressione Ctrl+C aqui).")
    try:
        while bm.ctx and bm.ctx.pages:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        bm.close()
