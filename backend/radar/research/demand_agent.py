"""demand_agent — validação de demanda fora da Meta (Google/Bing/DDG/Brave, Reddit, fóruns).

Salva as fontes como DemandEvidence. Se todas as buscas forem bloqueadas, a oferta fica
com demanda NOT_VERIFIED — nunca preenchida por suposição.
"""
from __future__ import annotations

from urllib.parse import urlparse

from radar.research.search_providers import MultiSearch, SearchHit
from radar.research.text_utils import PLATFORM_DOMAINS, norm_text

COMMUNITY_HOSTS = ("reddit.com", "quora.com", "facebook.com/groups", "tiktok.com", "youtube.com",
                   "instagram.com", "forum", "jusbrasil", "reclameaqui", "brainly")


def classify_hit(hit: SearchHit) -> str:
    host = urlparse(hit.url).netloc.lower()
    full = (hit.url or "").lower()
    text = norm_text(f"{hit.title} {hit.snippet}")
    if any(d in host for doms in PLATFORM_DOMAINS.values() for d in doms):
        return "concorrente"
    if "reclameaqui" in full:
        return "reclamacao"
    if any(h in full for h in COMMUNITY_HOSTS):
        return "comunidade"
    if "?" in (hit.title or "") or text.startswith(("como ", "por que", "porque", "o que ")):
        return "duvida"
    if any(w in text for w in ("ebook", "pdf", "curso", "guia", "planilha", "comprar", "r$")):
        return "concorrente"
    return "conteudo"


def demand_queries(phrase: str) -> list[str]:
    return [f"{phrase}", f"{phrase} como resolver", f"{phrase} reddit",
            f"{phrase} ebook OR pdf OR guia", f"{phrase} dúvida"]


def run_demand(search: MultiSearch, phrase: str, max_queries: int = 4) -> tuple[str, list[dict]]:
    """Retorna (status, evidências)."""
    evidence: list[dict] = []
    statuses = []
    for q in demand_queries(phrase)[:max_queries]:
        res = search.search(q, n=8)
        statuses.append(res.status)
        for h in res.hits:
            evidence.append({"source": res.provider, "query": q, "url": h.url, "title": h.title,
                             "snippet": h.snippet, "kind": classify_hit(h), "status": res.status})
        if not search.usable:
            break
    if evidence:
        status = "VERIFIED" if all(s == "VERIFIED" for s in statuses) else "PARTIAL"
    else:
        status = "BLOCKED" if "BLOCKED" in statuses else "NOT_VERIFIED"
    # remove duplicados por URL
    seen, uniq = set(), []
    for e in evidence:
        if e["url"] in seen:
            continue
        seen.add(e["url"])
        uniq.append(e)
    return status, uniq
