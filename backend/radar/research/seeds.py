"""Sementes comerciais iniciais. São só o ponto de partida: a expansão por palavras-chave
extraídas das ofertas encontradas (tabela keywords) passa a dominar com o tempo."""

COMMERCIAL_SEEDS = [
    "por apenas", "acesso imediato", "pagamento único", "garantia de 7 dias", "método",
    "protocolo", "desafio", "receitas", "atividades", "planilha", "checklist", "guia",
    "ebook", "pack", "apostila", "curso rápido", "passo a passo", "em 7 dias", "em 21 dias",
    "aprenda", "sem precisar", "imprima em casa", "material completo", "clique em saiba mais",
    "garanta agora", "material imprimível", "kit digital", "cardápio", "templates editáveis",
    "mini curso", "calendário", "receba no seu e-mail", "acesso vitalício",
]

PRICES = ["R$ 9,90", "R$ 14,90", "R$ 19,90", "R$ 27", "R$ 29,90", "R$ 37", "R$ 47", "R$ 67", "R$ 97"]

# Domínios de checkout: buscar o domínio no texto do anúncio pega o caption/link do criativo.
PLATFORM_QUERIES = [
    "pay.kiwify.com.br", "kiwify", "pay.hotmart.com", "hotmart", "pay.cakto.com.br", "cakto",
    "perfectpay", "eduzz", "monetizze",
]

PRICE_COMBOS = [
    "ebook R$ 19,90", "por apenas R$ 9,90", "por apenas R$ 27", "planilha R$ 27",
    "receitas R$ 19,90", "atividades R$ 14,90", "pack R$ 29,90", "protocolo R$ 37",
    "guia R$ 47", "apostila R$ 19,90",
]


def initial_keywords() -> list[tuple[str, str, float]]:
    """(termo, origem, prioridade)."""
    out = [(s, "seed", 1.0) for s in COMMERCIAL_SEEDS]
    out += [(p, "price", 0.9) for p in PRICES]
    out += [(p, "platform", 1.1) for p in PLATFORM_QUERIES]
    out += [(p, "price", 1.0) for p in PRICE_COMBOS]
    return out
