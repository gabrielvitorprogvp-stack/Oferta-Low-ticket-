"""Detector de aceleração — a métrica principal: QUEM ESTÁ ACELERANDO AGORA?

Trabalha sobre a série de snapshots (data, nº de criativos). Exemplos-alvo:
  12 → 18 em 3 dias      → FORTE
  18 → 19 em 7 dias      → FRACA
  80 → 80                → ESTAVEL (madura/parada)
  8 → 17 → 28            → FORTISSIMA (escala emergente)
Sem histórico, usa a curva retroativa das datas de início (estimada, menor confiança).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from radar.scoring.metrics import creative_growth_rate, delta_days

SIGNAL_RANK = {"QUEDA": -1, "SEM_DADOS": 0, "ESTAVEL": 1, "FRACA": 2, "MODERADA": 3, "FORTE": 4,
               "FORTISSIMA": 5}
MIN_STEP_HOURS = 10   # snapshots mais próximos que isso são agregados (evita ruído)


@dataclass
class Step:
    days: float
    start: int
    end: int

    @property
    def abs(self) -> int:
        return self.end - self.start

    @property
    def rel(self) -> float:
        return self.abs / max(self.start, 1)


@dataclass
class Acceleration:
    signal: str = "SEM_DADOS"
    estimated: bool = True
    basis: str = "none"            # snapshots | retro_curve
    delta_3d: int | None = None
    delta_7d: int | None = None
    delta_14d: int | None = None
    creative_growth_rate: float | None = None   # relativo/dia
    series: list = field(default_factory=list)
    explanation: str = ""

    @property
    def rank(self) -> int:
        return SIGNAL_RANK.get(self.signal, 0)

    def to_dict(self) -> dict:
        return asdict(self)


def _compact(series: list[tuple[datetime, int]]) -> list[tuple[datetime, int]]:
    out: list[tuple[datetime, int]] = []
    for t, c in sorted(series):
        if out and (t - out[-1][0]) < timedelta(hours=MIN_STEP_HOURS):
            out[-1] = (t, c)  # mantém o mais recente da janela
        else:
            out.append((t, c))
    return out


def classify_steps(steps: list[Step], latest: int) -> tuple[str, str]:
    if not steps:
        return "SEM_DADOS", "menos de 2 pontos na série"
    last = steps[-1]
    prev = steps[-2] if len(steps) >= 2 else None
    fmt = lambda s: f"{s.start}→{s.end} em {s.days:.0f}d"  # noqa: E731

    if last.rel <= -0.2 and last.abs <= -2:
        return "QUEDA", f"queda de criativos ({fmt(last)})"
    if prev and prev.abs >= 5 and last.abs >= 5 and prev.rel >= 0.25 and last.rel >= 0.25 \
            and last.days <= 10 and prev.days <= 10:
        return "FORTISSIMA", f"crescimento forte e sustentado ({prev.start}→{prev.end}→{last.end})"
    if last.abs >= 5 and last.rel >= 0.3 and last.days <= 5:
        return "FORTE", f"salto rápido de criativos ({fmt(last)})"
    if last.abs >= 4 and last.rel / max(last.days, 1) * 7 >= 0.5:
        return "FORTE", f"ritmo semanal ≥50% ({fmt(last)})"
    if last.abs >= 3 and last.rel >= 0.15 and last.days <= 8:
        return "MODERADA", f"crescimento moderado ({fmt(last)})"
    if last.abs > 0:
        return "FRACA", f"crescimento fraco ({fmt(last)})"
    if last.abs == 0:
        tail = "estável em volume alto — madura/parada" if latest >= 40 else "sem novos criativos"
        return "ESTAVEL", f"{tail} ({fmt(last)})"
    return "FRACA", f"leve queda ({fmt(last)})"


def analyze_series(series: list[tuple[datetime, int]]) -> Acceleration:
    pts = _compact(series)
    acc = Acceleration(series=[[t.isoformat(), c] for t, c in pts])
    if len(pts) < 2:
        return acc
    steps = [Step((t1 - t0).total_seconds() / 86400, c0, c1)
             for (t0, c0), (t1, c1) in zip(pts, pts[1:])]
    acc.signal, acc.explanation = classify_steps(steps, pts[-1][1])
    acc.estimated, acc.basis = False, "snapshots"
    acc.delta_3d = delta_days(pts, 3)
    acc.delta_7d = delta_days(pts, 7)
    acc.delta_14d = delta_days(pts, 14)
    acc.creative_growth_rate = creative_growth_rate(pts)
    return acc


def analyze_retro(retro_curve: list, now: datetime) -> Acceleration:
    """Estimativa a partir das datas de início dos criativos ativos hoje.
    retro_curve = [[dias_atrás, contagem], ...] (40,30,21,14,7,3,0)."""
    acc = Acceleration(basis="retro_curve", estimated=True)
    if not retro_curve:
        return acc
    d = {int(k): v for k, v in retro_curve}
    pts = [(now - timedelta(days=k), d[k]) for k in sorted(d, reverse=True) if k in (14, 7, 0)]
    acc.series = [[t.isoformat(), c] for t, c in pts]
    if len(pts) < 2 or d.get(0, 0) == 0:
        return acc
    steps = [Step(7, d.get(14, 0), d.get(7, 0)), Step(7, d.get(7, 0), d.get(0, 0))]
    sig, why = classify_steps(steps, d.get(0, 0))
    # sem histórico real, nunca passa de FORTE
    if sig == "FORTISSIMA":
        sig = "FORTE"
    acc.signal = sig
    acc.explanation = "estimado pelas datas de início: " + why + \
        " (viés de sobrevivência — confirmar com próximos snapshots)"
    acc.delta_3d = d.get(0, 0) - d.get(3, d.get(0, 0))
    acc.delta_7d = d.get(0, 0) - d.get(7, 0)
    acc.delta_14d = d.get(0, 0) - d.get(14, 0)
    return acc


def best_acceleration(series: list[tuple[datetime, int]], retro_curve: list, now: datetime
                      ) -> Acceleration:
    real = analyze_series(series)
    if not real.estimated:
        return real
    return analyze_retro(retro_curve, now)
