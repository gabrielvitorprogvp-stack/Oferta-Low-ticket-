"""Classificação de estágio (TESTE / ESCALA EMERGENTE / ESCALA MADURA) e status de watchlist."""
from __future__ import annotations

from radar.database.models import STAGE_EMERGING, STAGE_MATURE, STAGE_TEST, STAGE_UNKNOWN
from radar.scoring.acceleration import Acceleration
from radar.scoring.metrics import CreativeMetrics


def classify_stage(m: CreativeMetrics, acc: Acceleration, active_ads_total: int | None) -> tuple[str, str]:
    n = m.distinct_creatives
    total = max(active_ads_total or 0, m.observed_ads)
    if n == 0 and not total:
        return STAGE_UNKNOWN, "sem anúncios observados"
    new40_share = m.new_40d / n if n else 0
    old_share = m.old_active / n if n else 0

    if total >= 60 or n >= 45:
        if acc.rank >= 4 and new40_share >= 0.5:
            return STAGE_EMERGING, f"volume alto ({total}) mas ainda acelerando forte"
        return STAGE_MATURE, f"volume alto ({total} anúncios, {n} criativos), {old_share:.0%} antigos"
    if n >= 20 and old_share >= 0.6 and acc.rank <= 1 and (m.oldest_days or 0) > 90:
        return STAGE_MATURE, f"{n} criativos, maioria antiga e sem crescimento"
    if n <= 3 and acc.rank < 4:
        return STAGE_TEST, f"{n} criativo(s) — fase de teste"
    strong = acc.rank >= 4 and not acc.estimated
    if (n >= 10 and new40_share >= 0.5 and m.new_14d >= 3) or (n >= 6 and strong):
        return STAGE_EMERGING, (f"{n} criativos, {m.new_14d} novos em 14d, "
                                f"{m.old_active} antigos sobrevivendo; aceleração {acc.signal}")
    if n >= 6 and acc.rank >= 4:
        return STAGE_EMERGING, f"{n} criativos com aceleração {acc.signal} (estimada)"
    return STAGE_TEST, f"{n} criativos, {m.new_14d} novos em 14d — sem sinal claro de escala"


def status_for(stage: str, acc: Acceleration, velocity: float, discarded: bool = False,
               has_meta_data: bool = True) -> str:
    if discarded:
        return "DISCARDED"
    if not has_meta_data:
        return "NEW"
    if acc.signal == "QUEDA" and not acc.estimated:
        return "DECLINING"
    if stage == STAGE_EMERGING:
        return "EMERGING"
    if stage == STAGE_MATURE:
        return "MATURE"
    if velocity >= 30 or acc.rank >= 3:
        return "WATCHING"
    return "TESTING"
