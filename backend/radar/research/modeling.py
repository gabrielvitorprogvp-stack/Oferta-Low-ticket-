"""Modelagem de oportunidade: extrai dor, público, mecanismo, estrutura, ângulo e modelo
comercial — e sugere diferenciação PRÓPRIA. Nunca recomenda copiar marca, nome, textos,
criativos, imagens, PDFs ou vídeos do anunciante."""
from __future__ import annotations

import re

from radar.research.text_utils import norm_text

AUDIENCES = {
    "mães/pais": ["mae", "maes", "pais", "filho", "filha", "crianca"],
    "professores": ["professor", "professora", "educador", "sala de aula"],
    "mulheres 30+": ["mulher", "mulheres", "menopausa"],
    "profissionais de saúde": ["nutricionista", "fisioterapeuta", "profissional da saude", "terapeuta"],
    "empreendedores iniciantes": ["empreender", "renda extra", "vender", "negocio"],
    "concurseiros/candidatos": ["concurso", "vaga", "entrevista", "curriculo"],
    "tutores de pets": ["cachorro", "gato", "pet"],
    "artesãs": ["croche", "costura", "artesanato", "amigurumi"],
}

FORMAT_ALTERNATIVES = {
    "ebook": ["checklist diário imprimível", "desafio de 7 dias com acompanhamento", "planilha guiada"],
    "receitas": ["cardápio semanal com lista de compras", "receitas por faixa etária/objetivo",
                 "versão em vídeo curto passo a passo"],
    "cardapio": ["cardápio + lista de compras automática", "trilhas por objetivo"],
    "atividades": ["atividades por faixa etária com BNCC", "kit temático mensal", "versão gamificada"],
    "planilha": ["miniapp/calculadora", "planilha + vídeo de 10 min de uso", "templates por perfil"],
    "protocolo": ["desafio de 21 dias com checklist", "diário de acompanhamento imprimível"],
    "curso": ["mini curso de 1h focado num único resultado", "desafio de 5 dias"],
}


def build_modeling(*, texts: list[str], hooks: list[str], niche: str | None, product_format: str | None,
                   price: float | None, landing: dict | None, keyphrases: list[str]) -> dict:
    blob = norm_text(" ".join(texts))
    landing = landing or {}
    audience = [a for a, terms in AUDIENCES.items() if any(t in blob for t in terms)]
    pains = []
    for t in texts:
        for s in re.split(r"(?<=[.!?\n])\s*", t or ""):
            ns = norm_text(s)
            if 15 < len(ns) < 180 and re.search(r"nao aguenta|cansad|sofre|dificuldade|nao consegue|"
                                                r"chega de|pare de|medo|vergonha|preocup|problema", ns):
                pains.append(s.strip())
        if len(pains) >= 4:
            break
    angles = []
    for h in hooks[:12]:
        nh = norm_text(h)
        if "?" in h:
            angles.append("pergunta-dor")
        elif re.search(r"\d+ (dias|minutos|passos)", nh):
            angles.append("prazo/numérico")
        elif re.search(r"sem precisar|mesmo que|sem gastar", nh):
            angles.append("remoção de objeção")
        elif re.search(r"descobri|segredo|ninguem conta|poucos sabem", nh):
            angles.append("curiosidade/segredo")
        elif re.search(r"mae|professora|nutricionista|eu ", nh):
            angles.append("história/identificação")
        else:
            angles.append("benefício direto")
    angle_counts = {a: angles.count(a) for a in dict.fromkeys(angles)}
    commercial = {
        "preco": price,
        "formato": product_format,
        "garantia": landing.get("guarantee"),
        "order_bump": landing.get("order_bump"),
        "upsell": landing.get("upsell"),
        "bonus_count": len(landing.get("bonuses") or []),
        "funil": ("quiz" if landing.get("quiz") else "VSL" if landing.get("vsl") else "página de vendas"),
    }
    alt_formats = FORMAT_ALTERNATIVES.get(product_format or "", ["formato complementar (checklist, "
                                                                  "planilha ou desafio curto)"])
    underused = [a for a in ("pergunta-dor", "prazo/numérico", "remoção de objeção", "curiosidade/segredo",
                             "história/identificação") if a not in angle_counts]
    differentiation = [
        f"Recortar um sub-público específico dentro de '{niche or (keyphrases[0] if keyphrases else 'nicho')}'"
        + (f" (ex.: {audience[0]})" if audience else ""),
        f"Entregar em formato alternativo: {', '.join(alt_formats[:2])}",
        "Mecanismo próprio com nome próprio (não reutilizar o nome/método do concorrente)",
    ]
    if underused:
        differentiation.append(f"Testar ângulos pouco usados pelo anunciante: {', '.join(underused[:3])}")
    if price:
        differentiation.append(f"Ancoragem na mesma faixa (≈ R$ {price:.0f}) com bônus de implementação "
                               "diferente (ex.: checklist, grupo, áudio)")
    return {
        "dor": pains[:4],
        "publico": audience or ["não identificado"],
        "mecanismo": landing.get("mechanism"),
        "promessa": landing.get("promise"),
        "estrutura": (landing.get("structure") or [])[:10],
        "angulos": angle_counts,
        "modelo_comercial": commercial,
        "palavras_chave": keyphrases[:8],
        "diferenciacao_sugerida": differentiation,
        "aviso": ("Use apenas como inteligência de mercado: não copie marca, nome, identidade, "
                  "textos, criativos, imagens, PDFs, vídeos ou qualquer propriedade intelectual."),
    }
