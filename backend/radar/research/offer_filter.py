"""Triagem de candidatos: é produto digital low ticket com oferta direta?

Regras transparentes e auditáveis (cada decisão grava os motivos). Heurística — não é
verdade absoluta; por isso o resultado guarda `confidence` e os sinais usados.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from radar.research.text_utils import norm_text

FORMAT_TERMS = {
    "ebook": ["ebook", "e book", "e-book", "livro digital"],
    "pdf": ["pdf"],
    "guia": ["guia"],
    "protocolo": ["protocolo"],
    "desafio": ["desafio"],
    "receitas": ["receitas", "receituario"],
    "cardapio": ["cardapio"],
    "planilha": ["planilha"],
    "checklist": ["checklist"],
    "apostila": ["apostila"],
    "atividades": ["atividades", "atividade"],
    "material pedagogico": ["material pedagogico", "pedagogic"],
    "pack": ["pack", "pacote"],
    "templates": ["template", "templates", "modelos editaveis", "artes editaveis"],
    "mini curso": ["mini curso", "minicurso", "curso rapido", "aulas"],
    "treinamento": ["treinamento"],
    "calendario": ["calendario"],
    "metodo": ["metodo"],
    "calculadora": ["calculadora"],
    "app": ["aplicativo", "app "],
    "kit digital": ["kit digital", "kit"],
    "imprimivel": ["imprimivel", "imprima", "imprimir"],
    "curso": ["curso"],
}

DIGITAL_SIGNALS = ["acesso imediato", "receba no seu email", "receba no email", "download",
                   "digital", "pdf", "online", "acesso vitalicio", "pagamento unico",
                   "envio imediato", "100 online", "area de membros", "app"]

OFFER_SIGNALS = ["por apenas", "garanta", "compre", "comprar", "adquira", "oferta", "desconto",
                 "garantia", "de r$", "por r$", "promocao", "clique em saiba mais",
                 "saiba mais", "acesse", "link"]

EXCLUDE_TERMS = {
    "politica": ["deputado", "vereador", "prefeito", "senador", "eleicao", "candidato", "partido",
                 "governo federal", "prefeitura"],
    "imoveis": ["imovel", "imoveis", "apartamento", "lote ", "loteamento", "aluguel",
                "corretor de imoveis", "condominio"],
    "carros": ["seminovo", "concessionaria", "veiculo", "carro 0km", "test drive"],
    "servico local": ["agende sua consulta", "agende seu horario", "clinica", "consultorio",
                      "delivery", "cardapio do restaurante", "nosso endereco", "venha nos visitar",
                      "atendimento presencial", "estetica", "salao"],
    "high ticket": ["mentoria individual", "mentoria exclusiva", "consultoria", "imersao presencial",
                    "pos graduacao", "pos-graduacao", "mba", "faculdade", "vestibular"],
    "financeiro/regulado": ["emprestimo", "credito consignado", "cartao de credito", "seguro de vida",
                            "consorcio", "apostas", "bet ", "cassino"],
    "noticias": ["noticia", "jornal", "reportagem"],
    "ecommerce fisico": ["frete gratis", "entrega em todo brasil", "frete", "rastreio",
                         "pronta entrega", "tamanhos", "loja fisica"],
}

EXCLUDE_CATEGORIES = ["politician", "political", "government", "news", "real estate", "imobili",
                      "automotive", "car dealership", "restaurant", "hospital", "dentist",
                      "beauty salon", "clinic", "school", "university", "bank", "insurance"]

CHECKOUT_CTAS = {"SHOP_NOW", "LEARN_MORE", "BUY_NOW", "ORDER_NOW", "GET_OFFER", "SIGN_UP",
                 "DOWNLOAD", "SUBSCRIBE", "APPLY_NOW", "BOOK_NOW"}


@dataclass
class TriageResult:
    accepted: bool
    confidence: float
    product_format: str | None
    reasons: list[str] = field(default_factory=list)
    checks: dict = field(default_factory=dict)
    discard_reason: str | None = None


def detect_format(text: str) -> str | None:
    t = norm_text(text)
    for fmt, terms in FORMAT_TERMS.items():
        if any(term in t for term in terms):
            return fmt
    return None


def triage(texts: list[str], *, page_categories: list[str] | None = None, platform: str | None = None,
           price: float | None = None, cta_types: list[str] | None = None, has_link: bool = True,
           min_price: float = 10.0, max_price: float = 100.0) -> TriageResult:
    """Etapa B — valida se vale gastar tempo com o candidato."""
    blob = norm_text(" \n ".join(t for t in texts if t))
    reasons: list[str] = []
    cats = " ".join(page_categories or []).lower()

    fmt_hint = detect_format(blob)
    padded = f" {blob} "
    for label, terms in EXCLUDE_TERMS.items():
        hits = [t for t in terms if re.search(rf"\b{re.escape(t.strip())}\b", padded)]
        if not hits:
            continue
        # sinais de infoproduto (checkout de plataforma / formato digital) exigem evidência mais forte
        infoproduct = bool(platform) or bool(fmt_hint)
        needed = 3 if infoproduct else (1 if label in ("politica", "financeiro/regulado") else 2)
        if label == "ecommerce fisico" and platform:
            continue
        if len(hits) >= needed:
            return TriageResult(False, 0.7, None, [f"exclusão: {label} ({', '.join(hits[:3])})"],
                                discard_reason=f"exclusão: {label} ({', '.join(hits[:3])})")
    for c in EXCLUDE_CATEGORIES:
        if c in cats and not platform:
            return TriageResult(False, 0.6, None, [f"categoria de página excluída: {c}"],
                                discard_reason=f"categoria: {c}")

    fmt = detect_format(blob)
    digital = sum(1 for s in DIGITAL_SIGNALS if s in blob)
    offer = sum(1 for s in OFFER_SIGNALS if s in blob)
    cta_ok = bool(cta_types and any(c in CHECKOUT_CTAS for c in cta_types))

    checks = {
        "produto_real": bool(fmt or platform),
        "low_ticket": None if price is None else (min_price * 0.5 <= price <= max_price * 1.2),
        "oferta_direta": bool(offer or platform or cta_ok),
        "funil": bool(has_link),
        "resposta_direta": bool(cta_ok or offer >= 2),
    }
    if platform:
        reasons.append(f"checkout {platform}")
    if fmt:
        reasons.append(f"formato: {fmt}")
    if digital:
        reasons.append(f"{digital} sinais de produto digital")
    if price is not None:
        reasons.append(f"preço observado R$ {price:.2f}")

    if checks["low_ticket"] is False:
        return TriageResult(False, 0.75, fmt, reasons + ["preço fora da faixa low ticket"], checks,
                            discard_reason=f"preço R$ {price:.2f} fora da faixa")
    if not checks["produto_real"] and digital == 0:
        return TriageResult(False, 0.5, fmt, reasons + ["sem sinal de produto digital"], checks,
                            discard_reason="sem produto digital identificável")
    if not checks["oferta_direta"]:
        return TriageResult(False, 0.5, fmt, reasons + ["sem CTA/oferta direta"], checks,
                            discard_reason="sem oferta direta")
    if not has_link:
        return TriageResult(False, 0.5, fmt, reasons + ["sem link de destino"], checks,
                            discard_reason="sem landing page")

    conf = 0.35 + 0.2 * bool(platform) + 0.15 * bool(fmt) + 0.1 * min(digital, 2) / 2 \
        + 0.1 * cta_ok + 0.1 * (price is not None)
    return TriageResult(True, round(min(conf, 0.95), 2), fmt, reasons, checks)
