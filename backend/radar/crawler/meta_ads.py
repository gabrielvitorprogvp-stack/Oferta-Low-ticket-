"""meta_ads_agent — coleta na Meta Ads Library via Playwright.

Estratégia (validada na prática):
1. A 1ª página de resultados (~30 anúncios) vem embutida no HTML em JSON estruturado:
   id, data de início, collation (versões), formato, copy, CTA, link, página.
2. Páginas seguintes vêm por GraphQL ao rolar; sem login a Meta aplica rate limit
   agressivo ("Rate limit exceeded", code 1675004). Tentamos devagar; se limitar, o
   resultado fica PARTIAL (nunca extrapolamos o que não vimos).
3. Busca por anunciante (view_all_page_id) devolve o total de anúncios ativos da página —
   é o número usado nos snapshots. Para anunciantes pequenos/emergentes (<30 anúncios),
   a 1ª página já cobre 100% → VERIFIED.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable
from urllib.parse import urlencode

from playwright.sync_api import Error as PWError, Page, Response

from radar.config import get_settings
from radar.crawler.browser import BlockedError, BrowserManager


class ThrottledError(RuntimeError):
    """A Meta respondeu com a página de desafio/limite (__rd_verify em loop, ERR_TOO_MANY_RETRIES).
    É limitação de taxa: respeitamos com cooldown — nunca tentamos contornar."""
from radar.crawler.meta_parser import ParsedAd, parse_result_count_text, parse_search_blobs
from radar.database.models import BLOCKED, NOT_VERIFIED, PARTIAL, VERIFIED

log = logging.getLogger("radar.meta")

BASE = "https://www.facebook.com/ads/library/"
PT_MONTHS = {"jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6, "jul": 7, "ago": 8,
             "set": 9, "out": 10, "nov": 11, "dez": 12}


@dataclass
class MetaResult:
    status: str
    query: str
    total_count: int | None = None
    ads: list[ParsedAd] = field(default_factory=list)
    pages_loaded: int = 0
    rate_limited: bool = False
    error: str | None = None
    source: str = "json"  # json | dom

    @property
    def coverage(self) -> float | None:
        if not self.total_count:
            return 1.0 if self.total_count == 0 else None
        return round(min(1.0, len(self.ads) / self.total_count), 3)


def keyword_url(term: str, country: str, exact: bool = True) -> str:
    q = f'"{term}"' if exact else term
    return BASE + "?" + urlencode({
        "active_status": "active", "ad_type": "all", "country": country, "q": q,
        "search_type": "keyword_exact_phrase" if exact else "keyword_unordered",
        "media_type": "all"})


def page_url(page_id: str, country: str) -> str:
    return BASE + "?" + urlencode({
        "active_status": "active", "ad_type": "all", "country": country,
        "view_all_page_id": page_id, "search_type": "page", "media_type": "all"})


class MetaAdsClient:
    def __init__(self, bm: BrowserManager, emit: Callable[[str, str], None] | None = None):
        self.bm = bm
        self.s = get_settings()
        self.emit = emit or (lambda level, msg: log.log(getattr(logging, level), msg))
        self.consecutive_failures = 0
        self.blocked_reason: str | None = None
        self.throttle_events = 0
        self.throttled_reason: str | None = None

    @property
    def available(self) -> bool:
        return self.blocked_reason is None and self.throttled_reason is None and \
            self.consecutive_failures < self.s.meta_max_consecutive_failures

    # ------------------------------------------------------------------ API pública
    def search_keyword(self, term: str) -> MetaResult:
        res = self._with_retry(keyword_url(term, self.s.meta_country, exact=True), term, extra_pages=0)
        if res.status in (VERIFIED, PARTIAL) and not res.ads and res.total_count in (0, None):
            # consulta alternativa: termo solto em vez de frase exata
            alt = self._with_retry(keyword_url(term, self.s.meta_country, exact=False), term, 0)
            if alt.ads:
                return alt
        return res

    def search_page(self, page_id: str) -> MetaResult:
        return self._with_retry(page_url(page_id, self.s.meta_country), f"page:{page_id}",
                                extra_pages=self.s.meta_max_pages_per_advertiser)

    # ------------------------------------------------------------------ internos
    def _with_retry(self, url: str, label: str, extra_pages: int) -> MetaResult:
        if self.blocked_reason:
            return MetaResult(BLOCKED, label, error=self.blocked_reason)
        if self.throttled_reason:
            return MetaResult(NOT_VERIFIED, label, error=self.throttled_reason)
        last_err = None
        for attempt in range(self.s.meta_max_retries):
            try:
                res = self._load(url, label, extra_pages)
                self.consecutive_failures = 0
                return res
            except ThrottledError as e:
                self.throttle_events += 1
                if self.throttle_events > self.s.meta_max_cooldowns:
                    self.throttled_reason = f"limite de taxa persistente da Meta ({e})"
                    self.emit("ERROR", "Meta segue limitando após vários cooldowns — pausando Meta nesta "
                                       "rodada; candidatos ficam pendentes para a próxima. Dica: reduzir "
                                       "frequência, rodar de IP residencial ou com sessão logada "
                                       "(`python -m radar login`).")
                    return MetaResult(NOT_VERIFIED, label, error=self.throttled_reason)
                wait = self.s.meta_cooldown_s * (2 ** (self.throttle_events - 1))
                self.emit("WARNING", f"Meta limitou ({e}) em '{label}' — cooldown de {wait:.0f}s "
                                     f"({self.throttle_events}/{self.s.meta_max_cooldowns})")
                time.sleep(wait)
                last_err = str(e)
                continue
            except BlockedError as e:
                self.blocked_reason = str(e)
                self.emit("ERROR", f"Meta bloqueou ({e}). Pausando Meta nesta rodada; "
                                   f"rode `python -m radar login` para intervenção manual.")
                return MetaResult(BLOCKED, label, error=str(e))
            except Exception as e:  # noqa: BLE001 — qualquer falha vira retry
                last_err = f"{type(e).__name__}: {e}"[:300]
                wait = 3 * (2 ** attempt)
                self.emit("WARNING", f"Meta falhou em '{label}' (tentativa {attempt + 1}): "
                                     f"{last_err} — nova tentativa em {wait}s")
                time.sleep(wait)
                if attempt >= 1:
                    try:
                        self.bm.reopen()
                    except Exception as e2:  # noqa: BLE001
                        self.emit("ERROR", f"falha ao reabrir navegador: {e2}")
        self.consecutive_failures += 1
        return MetaResult(NOT_VERIFIED, label, error=last_err)

    def _load(self, url: str, label: str, extra_pages: int) -> MetaResult:
        self.bm.throttle("meta", self.s.meta_min_delay_s)
        page = self.bm.new_page()
        gql: list[str] = []

        def on_response(r: Response) -> None:
            if "/api/graphql" not in r.url:
                return
            try:
                if "AdLibrarySearchPaginationQuery" in (r.request.post_data or ""):
                    gql.append(r.text())
            except PWError:
                pass

        page.on("response", on_response)
        try:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
            except PWError as e:
                if "ERR_TOO_MANY_RETRIES" in str(e):
                    raise ThrottledError("ERR_TOO_MANY_RETRIES") from e
                raise
            blobs = self._wait_for_results(page)
            if not any("search_results_connection" in b for b in blobs):
                try:
                    html = page.content()
                except PWError:
                    html = ""
                if "__rd_verify" in html or len(html) < 2000:
                    raise ThrottledError("página de desafio __rd_verify em loop")
            try:
                body_text = page.inner_text("body", timeout=10000)
            except PWError:
                page.wait_for_timeout(2000)
                body_text = page.inner_text("body", timeout=10000)
            reason = self.bm.check_blocked(page, body_text)
            if reason:
                raise BlockedError(reason)
            sp = parse_search_blobs(blobs)
            if sp.captcha_required:
                raise BlockedError("Meta exige CAPTCHA (xfb_ad_library_is_captcha_required)")

            if not sp.ads and sp.total_count is None:
                # fallback DOM — estrutura JSON mudou ou não carregou
                dom_ads = parse_dom_cards(body_text)
                count = parse_result_count_text(body_text)
                if dom_ads or count is not None or "nenhum anúncio" in body_text.lower():
                    status = PARTIAL if dom_ads else (VERIFIED if count == 0 or count is None else PARTIAL)
                    return MetaResult(status, label, count if count is not None else len(dom_ads),
                                      dom_ads, 1, source="dom")
                raise RuntimeError("resultados não carregaram (sem JSON nem DOM reconhecível)")

            ads = {a.ad_archive_id: a for a in sp.ads}
            has_next, rate_limited, pages = sp.has_next_page, sp.rate_limited, 1
            while has_next and pages <= extra_pages and not rate_limited:
                n_before = len(gql)
                page.mouse.wheel(0, 20000)
                deadline = time.time() + 12
                while time.time() < deadline and len(gql) == n_before:
                    page.wait_for_timeout(500)
                if len(gql) == n_before:
                    break
                more = parse_search_blobs(gql[n_before:])
                if more.rate_limited:
                    rate_limited = True
                    self.emit("WARNING", f"Meta rate limit na paginação de '{label}' — "
                                         f"resultado parcial ({len(ads)} anúncios)")
                    break
                for a in more.ads:
                    ads[a.ad_archive_id] = a
                has_next = more.has_next_page
                pages += 1
                page.wait_for_timeout(int(self.s.meta_min_delay_s * 1000))

            total = sp.total_count
            complete = (not has_next) or (total is not None and len(ads) >= total)
            status = VERIFIED if complete else PARTIAL
            return MetaResult(status, label, total, list(ads.values()), pages, rate_limited)
        finally:
            try:
                page.close()
            except PWError:
                pass

    @staticmethod
    def _wait_for_results(page: Page, timeout_s: float = 25) -> list[str]:
        deadline = time.time() + timeout_s
        blobs: list[str] = []
        while time.time() < deadline:
            try:
                blobs = page.eval_on_selector_all(
                    'script[type="application/json"]',
                    "els => els.map(e => e.textContent).filter(t => t.includes('search_results_connection')"
                    " || t.includes('xfb_ad_library_is_captcha_required'))")
            except PWError:
                # a Meta serve um desafio JS que recarrega a página: espera a nova navegação
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=10000)
                except PWError:
                    pass
                blobs = []
            if any("search_results_connection" in b for b in blobs):
                return blobs
            page.wait_for_timeout(700)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=5000)
        except PWError:
            pass
        return blobs


def _pt_date(s: str) -> datetime | None:
    m = re.search(r"(\d{1,2}) de (\w{3})\w* de (\d{4})", s)
    if not m:
        return None
    mon = PT_MONTHS.get(m.group(2).lower()[:3])
    return datetime(int(m.group(3)), mon, int(m.group(1))) if mon else None


def parse_dom_cards(text: str) -> list[ParsedAd]:
    """Fallback textual dos cards (rótulos em pt-BR). Menos campos que o JSON."""
    out: list[ParsedAd] = []
    parts = re.split(r"Identificação da biblioteca:\s*", text or "")
    for chunk in parts[1:]:
        m = re.match(r"(\d+)", chunk)
        if not m:
            continue
        lines = [ln.strip() for ln in chunk.splitlines() if ln.strip() and ln.strip() != "​"]
        start = next((_pt_date(ln) for ln in lines if "Veiculação iniciada" in ln), None)
        name, body_lines, link = "", [], None
        try:
            i = next(i for i, ln in enumerate(lines) if ln == "Patrocinado")
            name = lines[i - 1]
            for ln in lines[i + 1:]:
                if re.fullmatch(r"[A-Z0-9.\-]+\.[A-Z]{2,}(\.[A-Z]{2})?", ln):
                    link = ln.lower()
                    break
                if ln in ("Ativo", "Inativo"):
                    break
                body_lines.append(ln)
        except StopIteration:
            pass
        out.append(ParsedAd(
            ad_archive_id=m.group(1), page_id="", page_name=name, collation_id=None,
            collation_count=None, is_active=True, start_date=start, end_date=None,
            display_format=None, body="\n".join(body_lines)[:2000] or None, title=None,
            link_url=f"https://{link}" if link else None, link_description=None, caption=link,
            cta_text=None, cta_type=None, page_url=None))
    return out
