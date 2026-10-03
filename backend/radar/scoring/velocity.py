"""Score de Velocidade de Escala (0–100) + confidence_score separado.

Pesos (conforme especificação):
  25% crescimento recente de criativos
  20% frequência de novos uploads
  20% sobrevivência de criativos antigos
  15% variedade de hooks
  10% variedade de formatos
  10% consistência do mesmo funil
Componentes não observáveis valem 0 no score E derrubam a confiança — nunca inventamos.
"""
from __future__ import annotations

from radar.scoring.acceleration import Acceleration
from radar.scoring.metrics import CreativeMetrics

WEIGHTS = {"growth": 25, "upload_freq": 20, "survival": 20, "hooks": 15, "formats": 10, "funnel": 10}


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def velocity_score(m: CreativeMetrics, acc: Acceleration, *, coverage: float | None,
                   n_snapshots: int, verification: str, source: str = "json") -> dict:
    comp: dict[str, float] = {}
    notes: list[str] = []
    n = m.distinct_creatives

    # 1) crescimento recente
    if not acc.estimated and acc.delta_7d is not None and n:
        base = max(n - acc.delta_7d, 1)
        comp["growth"] = _clamp((acc.delta_7d / base) / 1.0) * 0.7 + _clamp(acc.delta_7d / 12) * 0.3
    elif not acc.estimated and acc.creative_growth_rate is not None:
        comp["growth"] = _clamp(acc.creative_growth_rate * 7)
    elif n:
        share = m.new_14d / n
        comp["growth"] = _clamp(share) * 0.5 + _clamp(m.new_14d / 10) * 0.5
        notes.append("crescimento estimado por datas de início (sem histórico)")
    else:
        comp["growth"] = 0.0

    # 2) frequência de novos uploads (dias distintos com criativo novo nos últimos 14d)
    comp["upload_freq"] = _clamp(m.upload_days_14d / 7) * 0.6 + _clamp(m.new_7d / 7) * 0.4

    # 3) sobrevivência de criativos antigos (vencedores que seguem rodando)
    comp["survival"] = _clamp(m.old_active / 5)

    # 4) hooks e 5) formatos
    comp["hooks"] = _clamp(m.hooks_count / 8)
    nf = len([f for f in m.formats if f != "DESCONHECIDO"])
    comp["formats"] = {0: 0.0, 1: 0.3, 2: 0.7}.get(nf, 1.0)

    # 6) consistência do funil
    if m.top_url_share is None:
        comp["funnel"] = 0.0
        notes.append("sem URL de destino observável")
    else:
        comp["funnel"] = _clamp((m.top_url_share - 0.2) / 0.5)

    score = sum(WEIGHTS[k] * v for k, v in comp.items())
    if n <= 2:
        score = min(score, 25)
        notes.append("≤2 criativos: fase de teste, score limitado")

    # ---------- confiança ----------
    conf = 100.0
    if verification == "NOT_VERIFIED":
        conf = 10.0
    if coverage is not None and coverage < 1:
        conf -= (1 - coverage) * 45
        notes.append(f"cobertura parcial dos anúncios ({coverage:.0%})")
    elif coverage is None:
        conf -= 20
    if n_snapshots <= 1:
        conf -= 25
    elif n_snapshots == 2:
        conf -= 12
    if acc.estimated:
        conf -= 5
    if m.observed_ads and m.missing_start / max(m.distinct_creatives, 1) > 0.2:
        conf -= 15
        notes.append("datas de início ausentes em parte dos criativos")
    if source == "dom":
        conf -= 15
    if n < 3:
        conf -= 10

    return {
        "score": round(score, 1),
        "confidence": round(max(5.0, min(95.0, conf)), 1),
        "components": {k: round(v * WEIGHTS[k], 1) for k, v in comp.items()},
        "notes": notes,
    }
