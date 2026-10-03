"""landing_page_agent — abre a página de vendas e extrai a estrutura da oferta.

Extração heurística (regex + estrutura de headings). Tudo que não for encontrado fica
como None/[] — nunca preenchemos por suposição.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from playwright.sync_api import Error as PWError

from radar.crawler.browser import BlockedError, BrowserManager
from radar.database.models import BLOCKED, NOT_VERIFIED, PARTIAL, VERIFIED
from radar.research.text_utils import (PLATFORM_DOMAINS, detect_platform, extract_prices_brl,
                                       guess_offer_price, has_foreign_currency)

JS_EXTRACT = """
() => {
  const q = s => Array.from(document.querySelectorAll(s));
  const txt = e => (e.innerText || '').trim().replace(/\\s+/g, ' ');
  return {
    title: document.title,
    h1: q('h1').map(txt).filter(Boolean).slice(0, 5),
    h2: q('h2').map(txt).filter(Boolean).slice(0, 25),
    h3: q('h3').map(txt).filter(Boolean).slice(0, 25),
    links: q('a[href]').map(a => ({href: a.href, text: txt(a).slice(0, 80)})).slice(0, 400),
    buttons: q('button, a.button, .btn, [role=button], input[type=submit]').map(txt)
               .filter(Boolean).slice(0, 40),
    videos: q('video, iframe').map(e => e.src || e.getAttribute('data-src') || '').filter(Boolean),
    scripts: q('script[src]').map(s => s.src).slice(0, 80),
    forms: q('form').length,
    inputs_radio: q('input[type=radio]').length,
    lis: q('li').map(txt).filter(t => t.length > 3 && t.length < 160).slice(0, 80),
    imgs: q('img').length,
  };
}
"""

VSL_HOSTS = ("youtube.com", "youtu.be", "vimeo.com", "vturb", "converteai", "pandavideo",
             "wistia", "vidalytics", "smartplayer", "scripts.converteai")


@dataclass
class LandingData:
    status: str = NOT_VERIFIED
    url: str = ""
    final_url: str | None = None
    title: str | None = None
    headline: str | None = None
    subheadline: str | None = None
    promise: str | None = None
    mechanism: str | None = None
    price_brl: float | None = None
    price_old_brl: float | None = None
    prices_seen: list[float] = field(default_factory=list)
    currency_note: str | None = None
    deliverables: list[str] = field(default_factory=list)
    bonuses: list[str] = field(default_factory=list)
    proof: list[str] = field(default_factory=list)
    testimonials: int = 0
    guarantee: str | None = None
    urgency: list[str] = field(default_factory=list)
    ctas: list[str] = field(default_factory=list)
    checkout_url: str | None = None
    checkout_platform: str | None = None
    checkout_price_brl: float | None = None
    order_bump: bool | None = None
    upsell: bool | None = None
    quiz: bool = False
    vsl: bool = False
    structure: list[str] = field(default_factory=list)
    screenshot: str | None = None
    text_excerpt: str | None = None
    error: str | None = None

    def to_json(self) -> dict:
        d = asdict(self)
        for k in ("url", "final_url", "title", "screenshot", "text_excerpt", "error", "status"):
            d.pop(k, None)
        return d


def _find(pattern: str, text: str, flags=re.I) -> str | None:
    m = re.search(pattern, text, flags)
    return m.group(0).strip()[:220] if m else None


def _lines_with(text: str, words: tuple[str, ...], limit: int = 8, max_len: int = 160) -> list[str]:
    out = []
    for ln in text.splitlines():
        s = ln.strip()
        if 4 < len(s) <= max_len and any(w in s.lower() for w in words) and s not in out:
            out.append(s)
            if len(out) >= limit:
                break
    return out


def analyze_text(text: str, dom: dict, data: LandingData) -> LandingData:
    """Parte pura (testável) da extração."""
    low = text.lower()
    h1, h2 = dom.get("h1") or [], dom.get("h2") or []
    data.headline = (h1[0] if h1 else (h2[0] if h2 else None))
    rest = (h1[1:] + h2) if h1 else h2[1:]
    data.subheadline = rest[0] if rest else None
    data.structure = [h for h in (h1 + h2)][:25]

    data.promise = _find(r"[^.\n]{0,90}(em (até )?\d+ dias|sem precisar|mesmo que|de forma simples|"
                         r"passo a passo|garantid[oa]s?)[^.\n]{0,90}", text)
    data.mechanism = _find(r"[^.\n]{0,60}\b(método|protocolo|técnica|sistema|estratégia|fórmula)\b"
                           r"[^.\n]{0,100}", text)
    prices = extract_prices_brl(text)
    data.prices_seen = prices[:15]
    data.price_brl, data.price_old_brl = guess_offer_price(prices, text)
    if not prices and has_foreign_currency(text):
        data.currency_note = "preço exibido em moeda estrangeira (provável conversão por IP) — ignorado"

    data.bonuses = _lines_with(text, ("bônus", "bonus"), 10)
    data.deliverables = _lines_with(text, ("você vai receber", "voce vai receber", "o que você recebe",
                                           "módulo", "modulo", "ebook", "e-book", "pdf", "receitas",
                                           "planilha", "acesso a", "aulas"), 12)
    data.proof = _lines_with(text, ("alunos", "clientes", "pessoas já", "vendidos", "avaliações",
                                    "estrelas", "comprovado", "+ de"), 6)
    data.testimonials = len(re.findall(r"depoimento|avaliaç|o que dizem|★|⭐", low))
    data.guarantee = _find(r"garantia (incondicional )?de \d+ dias|\d+ dias de garantia|"
                           r"garantia (incondicional|total)", text)
    data.urgency = _lines_with(text, ("por tempo limitado", "últimas vagas", "ultimas vagas",
                                      "somente hoje", "só hoje", "acaba em", "expira", "promoção termina",
                                      "vagas limitadas", "oferta encerra"), 5)
    if re.search(r"\b\d{2}:\d{2}(:\d{2})?\b", text) and "tempo" in low:
        data.urgency.append("contador regressivo")
    ctas = [b for b in (dom.get("buttons") or []) if 2 < len(b) < 60]
    data.ctas = list(dict.fromkeys(ctas))[:10]

    checkout = None
    for lk in dom.get("links") or []:
        href = (lk.get("href") or "").lower()
        if any(d in href for doms in PLATFORM_DOMAINS.values() for d in doms):
            checkout = lk["href"]
            break
    data.checkout_url = checkout
    data.checkout_platform = detect_platform(checkout, data.final_url, data.url)
    data.vsl = any(h in v for v in (dom.get("videos") or []) + (dom.get("scripts") or [])
                   for h in VSL_HOSTS)
    data.quiz = bool(re.search(r"\bquiz\b|responda (as|algumas) perguntas|pergunta \d+ de \d+", low)) \
        or (dom.get("inputs_radio", 0) >= 3 and dom.get("forms", 0) >= 1)
    data.order_bump = True if re.search(r"order ?bump|adicione também|leve também|aproveite e leve",
                                        low) else None
    data.upsell = True if re.search(r"upsell|oferta especial (só|somente) para|não feche esta página",
                                    low) else None
    return data


def analyze_landing(bm: BrowserManager, url: str, shot_name: str, follow_checkout: bool = True
                    ) -> LandingData:
    data = LandingData(url=url)
    bm.throttle("landing", 2.0)
    page = bm.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except PWError:
            pass
        page.mouse.wheel(0, 4000)
        page.wait_for_timeout(1500)
        text = page.inner_text("body", timeout=10000)
        reason = bm.check_blocked(page, text)
        if reason:
            raise BlockedError(reason)
        dom = page.evaluate(JS_EXTRACT)
        data.final_url = page.url
        data.title = dom.get("title")
        analyze_text(text, dom, data)
        data.text_excerpt = text[:6000]
        data.screenshot = bm.screenshot(page, shot_name)
        data.status = VERIFIED if (data.headline or data.price_brl) else PARTIAL

        # checkout: pega preço/order bump quando a landing não mostra preço em R$
        if follow_checkout and data.checkout_url and data.price_brl is None:
            try:
                bm.throttle("landing", 2.0)
                page.goto(data.checkout_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2500)
                ctext = page.inner_text("body", timeout=8000)
                cprices = extract_prices_brl(ctext)
                if cprices:
                    data.checkout_price_brl = guess_offer_price(cprices, ctext)[0]
                    data.price_brl = data.checkout_price_brl
                elif has_foreign_currency(ctext):
                    data.currency_note = ("checkout exibiu moeda estrangeira (conversão por IP fora do "
                                          "Brasil) — preço não registrado")
                if re.search(r"adicione também|leve também|order ?bump|sim, eu quero", ctext.lower()):
                    data.order_bump = True
            except PWError:
                pass
    except BlockedError as e:
        data.status, data.error = BLOCKED, str(e)
    except PWError as e:
        data.status, data.error = NOT_VERIFIED, str(e)[:300]
    finally:
        try:
            page.close()
        except PWError:
            pass
    return data
