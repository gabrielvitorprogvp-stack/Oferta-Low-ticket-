"""Busca web plugável. Ordem configurável em SEARCH_PROVIDERS.

- brave_api: API oficial (precisa BRAVE_API_KEY) — a opção mais estável.
- bing / duckduckgo / google: via navegador. Em IP de datacenter costumam devolver CAPTCHA
  ou página vazia; o provider detecta e marca BLOCKED/NOT_VERIFIED (sem contornar).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from urllib.parse import quote_plus, urlparse

import httpx
from playwright.sync_api import Error as PWError

from radar.config import get_settings
from radar.crawler.browser import BrowserManager
from radar.database.models import BLOCKED, NOT_VERIFIED, VERIFIED

log = logging.getLogger("radar.search")


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str = ""


@dataclass
class SearchResult:
    provider: str
    query: str
    status: str
    hits: list[SearchHit] = field(default_factory=list)
    error: str | None = None


class BraveAPI:
    name = "brave_api"

    def __init__(self, key: str):
        self.key = key

    def search(self, q: str, n: int = 10) -> SearchResult:
        if not self.key:
            return SearchResult(self.name, q, NOT_VERIFIED, error="BRAVE_API_KEY ausente")
        try:
            r = httpx.get("https://api.search.brave.com/res/v1/web/search",
                          params={"q": q, "count": n, "country": "BR", "search_lang": "pt-br"},
                          headers={"X-Subscription-Token": self.key, "Accept": "application/json"},
                          timeout=20)
            if r.status_code == 429:
                return SearchResult(self.name, q, BLOCKED, error="rate limit")
            r.raise_for_status()
            res = (r.json().get("web") or {}).get("results") or []
            hits = [SearchHit(x.get("title", ""), x.get("url", ""), x.get("description", "")) for x in res]
            return SearchResult(self.name, q, VERIFIED, hits)
        except httpx.HTTPError as e:
            return SearchResult(self.name, q, NOT_VERIFIED, error=str(e)[:200])


BROWSER_ENGINES = {
    "bing": ("https://www.bing.com/search?q={q}&setlang=pt-br&cc=BR", "li.b_algo",
             "h2 a", ".b_caption p, .b_lineclamp2"),
    "duckduckgo": ("https://html.duckduckgo.com/html/?q={q}&kl=br-pt", ".result",
                   "a.result__a", ".result__snippet"),
    "google": ("https://www.google.com/search?q={q}&hl=pt-BR&gl=br&num=10", "div.g, div.MjjYud",
               "a:has(h3)", "div.VwiC3b"),
}
ENGINE_HOSTS = ("bing.com", "duckduckgo.com", "google.", "microsoft.com", "msn.com")


class BrowserSearch:
    def __init__(self, bm: BrowserManager, engine: str):
        self.bm, self.name = bm, engine
        self.blocked = False

    def search(self, q: str, n: int = 10) -> SearchResult:
        if self.blocked:
            return SearchResult(self.name, q, BLOCKED, error="bloqueado anteriormente nesta rodada")
        url_t, item_sel, link_sel, snip_sel = BROWSER_ENGINES[self.name]
        self.bm.throttle(self.name, 4.0)
        page = self.bm.new_page()
        try:
            page.goto(url_t.format(q=quote_plus(q)), wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)
            reason = self.bm.check_blocked(page)
            if reason:
                self.blocked = True
                return SearchResult(self.name, q, BLOCKED, error=reason)
            hits = []
            for it in page.query_selector_all(item_sel)[: n * 2]:
                a = it.query_selector(link_sel)
                if not a:
                    continue
                href = a.get_attribute("href") or ""
                if href.startswith("//duckduckgo.com/l/") or "uddg=" in href:
                    from urllib.parse import parse_qs, unquote
                    href = unquote(parse_qs(urlparse(href).query).get("uddg", [href])[0])
                if not href.startswith("http") or any(h in urlparse(href).netloc for h in ENGINE_HOSTS):
                    continue
                sn = it.query_selector(snip_sel)
                hits.append(SearchHit((a.inner_text() or "").strip(), href,
                                      (sn.inner_text() if sn else "").strip()[:400]))
                if len(hits) >= n:
                    break
            status = VERIFIED if hits else NOT_VERIFIED
            return SearchResult(self.name, q, status, hits, None if hits else "nenhum resultado legível")
        except PWError as e:
            return SearchResult(self.name, q, NOT_VERIFIED, error=str(e)[:200])
        finally:
            try:
                page.close()
            except PWError:
                pass


class MultiSearch:
    """Tenta os providers em ordem até um retornar resultados."""

    def __init__(self, bm: BrowserManager | None):
        s = get_settings()
        self.providers = []
        for name in [p.strip() for p in s.search_providers.split(",") if p.strip()]:
            if name == "brave_api":
                if s.brave_api_key:
                    self.providers.append(BraveAPI(s.brave_api_key))
            elif name in BROWSER_ENGINES and bm is not None:
                self.providers.append(BrowserSearch(bm, name))

    def search(self, q: str, n: int = 10) -> SearchResult:
        last = SearchResult("none", q, NOT_VERIFIED, error="nenhum provider configurado")
        for p in self.providers:
            if getattr(p, "blocked", False):
                continue
            res = p.search(q, n)
            if res.hits:
                return res
            last = res
        return last

    @property
    def usable(self) -> bool:
        return any(not getattr(p, "blocked", False) for p in self.providers)
