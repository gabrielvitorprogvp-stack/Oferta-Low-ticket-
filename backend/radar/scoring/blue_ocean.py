"""Score Mar Azul (0–100) + confidence_score.

Heurístico e explicável: cada componente guarda o valor e a evidência. Componentes sem
evidência entram como neutros (0.5) e reduzem a confiança.
"""
from __future__ import annotations

from radar.research.text_utils import norm_text

PAIN_TERMS = ["nao aguenta", "cansad", "sofre", "sofrimento", "dificuldade", "problema", "dor ",
              "medo", "vergonha", "nao consegue", "sem conseguir", "frustr", "desesper", "chega de",
              "pare de", "nunca mais", "ansiedade", "estresse", "preocup", "luta", "nao sabe",
              "inseguran", "culpa", "sozinh", "nao come", "birra", "travad"]
DESIRE_TERMS = ["sonho", "conquistar", "transformar", "finalmente", "liberdade", "renda", "lucrar",
                "economizar", "resultado", "rapido", "facil", "simples"]
EASY_FORMATS = {"ebook": 1.0, "pdf": 1.0, "guia": 1.0, "checklist": 1.0, "planilha": 0.95,
                "receitas": 1.0, "cardapio": 1.0, "apostila": 0.95, "atividades": 0.95,
                "imprimivel": 1.0, "material pedagogico": 0.9, "templates": 0.85, "pack": 0.85,
                "calendario": 0.95, "protocolo": 0.9, "desafio": 0.8, "metodo": 0.75,
                "kit digital": 0.85, "mini curso": 0.65, "treinamento": 0.55, "curso": 0.5,
                "calculadora": 0.5, "app": 0.35}
WEIGHTS = {"pain": 15, "clarity": 10, "intent": 10, "competition": 15, "similar": 10,
           "differentiation": 10, "own_version": 10, "delivery": 8, "creative_power": 6,
           "low_cost": 6}


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def blue_ocean_score(*, texts: list[str], product_format: str | None, price: float | None,
                     platform: str | None, has_promise: bool, landing_verified: bool,
                     cluster_advertisers: int | None, niche_meta_results: int | None,
                     hooks_count: int, formats_count: int, video_share: float,
                     demand_evidence: int, specific_niche: bool) -> dict:
    blob = " " + norm_text(" ".join(t for t in texts if t)) + " "
    comp: dict[str, float] = {}
    ev: dict[str, str] = {}
    unknown = 0

    pain_hits = sum(1 for t in PAIN_TERMS if t in blob)
    desire_hits = sum(1 for t in DESIRE_TERMS if t in blob)
    comp["pain"] = _clamp(pain_hits / 4) * 0.75 + _clamp(desire_hits / 4) * 0.25
    ev["pain"] = f"{pain_hits} termos de dor, {desire_hits} de desejo"

    comp["clarity"] = (0.35 * (price is not None) + 0.35 * bool(product_format) + 0.3 * has_promise)
    ev["clarity"] = f"preço={'sim' if price else 'não'}, formato={product_format}, promessa={has_promise}"

    comp["intent"] = 0.5 * bool(platform) + 0.3 * (price is not None and price <= 100) + \
        0.2 * ("garantia" in blob)
    ev["intent"] = f"checkout={platform}"

    if cluster_advertisers is None:
        comp["competition"], unknown = 0.5, unknown + 1
        ev["competition"] = "sem dados de cluster"
    else:
        comp["competition"] = _clamp(1 - (cluster_advertisers - 2) / 13)
        ev["competition"] = f"{cluster_advertisers} anunciantes monitorados no mesmo cluster"

    if niche_meta_results is None:
        comp["similar"], unknown = 0.5, unknown + 1
        ev["similar"] = "volume de anúncios do nicho não medido"
    else:
        # ~<50 anúncios ativos com o termo = mar azul; >2000 = oceano vermelho
        r = niche_meta_results
        comp["similar"] = 1.0 if r <= 50 else 0.0 if r >= 2000 else _clamp(1 - (r - 50) / 1950)
        ev["similar"] = f"~{r} anúncios ativos na Meta com o termo do nicho"

    comp["differentiation"] = 0.7 if specific_niche else 0.4
    ev["differentiation"] = "nicho específico" if specific_niche else "nicho genérico"

    fmt_ease = EASY_FORMATS.get(product_format or "", 0.5)
    if not product_format:
        unknown += 1
    comp["own_version"] = fmt_ease
    comp["delivery"] = fmt_ease
    comp["low_cost"] = _clamp(fmt_ease + 0.05)
    ev["own_version"] = f"formato {product_format or 'desconhecido'}"

    comp["creative_power"] = _clamp(hooks_count / 6) * 0.6 + _clamp(formats_count / 3) * 0.2 + \
        _clamp(video_share) * 0.2
    ev["creative_power"] = f"{hooks_count} hooks, {formats_count} formatos"

    score = sum(WEIGHTS[k] * v for k, v in comp.items())
    conf = 35 + 20 * landing_verified + 10 * (price is not None) + \
        10 * (cluster_advertisers is not None and cluster_advertisers >= 3) + \
        10 * (niche_meta_results is not None) + min(demand_evidence, 3) * 5 - unknown * 5
    return {
        "score": round(score, 1),
        "confidence": round(max(5, min(90, conf)), 1),
        "components": {k: round(v * WEIGHTS[k], 1) for k, v in comp.items()},
        "evidence": ev,
    }
