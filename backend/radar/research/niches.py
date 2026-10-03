"""Rotulagem de nicho. A taxonomia é só um vocabulário de rótulos; quando nada casa, o
nicho vira a palavra-chave dominante da oferta (descoberta aberta, sem nicho pré-escolhido)."""
from __future__ import annotations

from radar.research.text_utils import extract_keyphrases, norm_text

NICHE_LEXICON = {
    "Infantil / Maternidade": ["crianca", "filho", "bebe", "maternidade", "mae ", "maes", "infantil",
                               "introducao alimentar", "seletividade", "autismo", "tdah", "birra"],
    "Educação / Pedagógico": ["professor", "professora", "alfabetizacao", "pedagogic", "sala de aula",
                              "atividades", "bncc", "educacao infantil", "escola"],
    "Emagrecimento / Dieta": ["emagrecer", "emagrecimento", "dieta", "barriga", "quilos", "kg",
                              "low carb", "jejum", "detox", "cha "],
    "Receitas / Culinária": ["receitas", "receita", "bolo", "doces", "marmita", "confeitaria",
                             "salgados", "airfryer", "air fryer", "cardapio"],
    "Saúde / Bem-estar": ["ansiedade", "dor ", "dores", "sono", "insonia", "saude", "diabetes",
                          "pressao", "intestino", "menopausa", "fibromialgia"],
    "Fitness": ["treino", "academia", "gluteo", "musculacao", "abdomen", "pilates", "yoga"],
    "Beleza / Autocuidado": ["cabelo", "pele", "skincare", "unhas", "maquiagem", "cachos"],
    "Relacionamento": ["relacionamento", "casamento", "conquistar", "ex ", "namoro", "seducao"],
    "Espiritualidade / Religião": ["oracao", "deus", "biblia", "jesus", "espiritual", "salmo", "fe "],
    "Finanças / Renda extra": ["renda extra", "dinheiro", "dividas", "financas", "investir",
                               "ganhar dinheiro", "vender"],
    "Carreira / Concursos": ["concurso", "curriculo", "entrevista", "linkedin", "emprego", "carreira"],
    "Artesanato / Costura": ["croche", "costura", "artesanato", "amigurumi", "bordado", "moldes",
                             "papelaria", "topo de bolo", "festa"],
    "Pets": ["cachorro", "gato", "pet ", "caes", "adestramento"],
    "Idiomas": ["ingles", "espanhol", "idioma", "fluencia"],
    "Produtividade / Planilhas": ["planilha", "excel", "organizacao", "planner", "produtividade",
                                  "notion"],
    "Marketing digital": ["instagram", "trafego", "marketing", "seguidores", "canva", "social media",
                          "copy", "tiktok"],
}


def detect_niche(texts: list[str]) -> tuple[str | None, list[str]]:
    blob = " " + norm_text(" ".join(t for t in texts if t)) + " "
    best, best_hits = None, 0
    for niche, terms in NICHE_LEXICON.items():
        hits = sum(blob.count(t) for t in terms)
        if hits > best_hits:
            best, best_hits = niche, hits
    phrases = extract_keyphrases([t for t in texts if t], top=6)
    if best and best_hits >= 2:
        return best, phrases
    if phrases:
        return phrases[0].title(), phrases
    return best, phrases
