"""Métricas de comportamento publicitário a partir dos anúncios observados.

"Criativo" = fingerprint (texto + título + formato + mídia). Várias ad IDs com o mesmo
fingerprint são duplicação técnica e contam como 1 criativo.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Iterable, Protocol

from radar.research.text_utils import norm_text, normalize_url

OLD_DAYS = 30           # criativo "antigo sobrevivente": rodando há 30+ dias
RETRO_POINTS = (40, 30, 21, 14, 7, 3, 0)


class AdLike(Protocol):
    fingerprint: str
    start_date: datetime | None
    display_format: str | None
    link_url: str | None

    @property
    def hook(self) -> str | None: ...


@dataclass
class CreativeMetrics:
    observed_ads: int = 0
    distinct_creatives: int = 0
    new_7d: int = 0
    new_14d: int = 0
    new_30d: int = 0
    new_40d: int = 0
    old_active: int = 0
    hooks_count: int = 0
    formats: dict = field(default_factory=dict)
    upload_days_14d: int = 0
    top_url: str | None = None
    top_url_share: float | None = None
    urls_count: int = 0
    missing_start: int = 0
    oldest_days: int | None = None
    median_age_days: float | None = None
    retro_curve: list = field(default_factory=list)  # [(dias_atrás, criativos ativos que já existiam)]
    hooks: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _hook_of(ad) -> str | None:
    h = getattr(ad, "hook", None)
    return norm_text(h)[:80] if h else None


def compute_metrics(ads: Iterable[AdLike], now: datetime) -> CreativeMetrics:
    ads = list(ads)
    m = CreativeMetrics(observed_ads=len(ads))
    if not ads:
        return m
    creatives: dict[str, dict] = {}
    for a in ads:
        c = creatives.setdefault(a.fingerprint, {"start": None, "format": a.display_format,
                                                 "hook": _hook_of(a), "raw_hook": getattr(a, "hook", None)})
        if a.start_date and (c["start"] is None or a.start_date < c["start"]):
            c["start"] = a.start_date
    m.distinct_creatives = len(creatives)

    ages = []
    upload_days = set()
    for c in creatives.values():
        if c["start"] is None:
            m.missing_start += 1
            continue
        age = (now - c["start"]).total_seconds() / 86400
        ages.append(age)
        if age <= 7:
            m.new_7d += 1
        if age <= 14:
            m.new_14d += 1
            upload_days.add(c["start"].date())
        if age <= 30:
            m.new_30d += 1
        if age <= 40:
            m.new_40d += 1
        if age >= OLD_DAYS:
            m.old_active += 1
    m.upload_days_14d = len(upload_days)
    if ages:
        ages.sort()
        m.oldest_days = int(ages[-1])
        mid = len(ages) // 2
        m.median_age_days = round(ages[mid] if len(ages) % 2 else (ages[mid - 1] + ages[mid]) / 2, 1)
        # curva retroativa: quantos criativos ativos hoje já existiam há N dias.
        # Viés de sobrevivência: subestima o passado (criativos pausados não aparecem).
        m.retro_curve = [[d, sum(1 for a in ages if a >= d)] for d in RETRO_POINTS]

    hooks = [c["hook"] for c in creatives.values() if c["hook"]]
    m.hooks_count = len(set(hooks))
    raw = {}
    for c in creatives.values():
        if c["hook"] and c["hook"] not in raw:
            raw[c["hook"]] = c["raw_hook"]
    m.hooks = list(raw.values())[:30]
    m.formats = dict(Counter((c["format"] or "DESCONHECIDO") for c in creatives.values()))

    urls = Counter(normalize_url(a.link_url) for a in ads if a.link_url and normalize_url(a.link_url))
    if urls:
        top, n = urls.most_common(1)[0]
        m.top_url, m.top_url_share, m.urls_count = top, round(n / sum(urls.values()), 2), len(urls)
    return m


def creative_growth_rate(series: list[tuple[datetime, int]]) -> float | None:
    """Crescimento relativo por dia entre o 1º e o último snapshot."""
    if len(series) < 2:
        return None
    (t0, c0), (t1, c1) = series[0], series[-1]
    days = max((t1 - t0).total_seconds() / 86400, 0.5)
    return round(((c1 - c0) / max(c0, 1)) / days, 4)


def delta_days(series: list[tuple[datetime, int]], days: int) -> int | None:
    """Variação de criativos versus o snapshot mais próximo de N dias atrás."""
    if len(series) < 2:
        return None
    t_last, c_last = series[-1]
    target = t_last - timedelta(days=days)
    tol = timedelta(days=max(1.0, days * 0.5))
    best = None
    for t, c in series[:-1]:
        if abs(t - target) <= tol and (best is None or abs(t - target) < abs(best[0] - target)):
            best = (t, c)
    return None if best is None else c_last - best[1]
