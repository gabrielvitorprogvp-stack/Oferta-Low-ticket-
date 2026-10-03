from dataclasses import dataclass
from datetime import datetime, timedelta

from radar.scoring.acceleration import analyze_retro, analyze_series
from radar.scoring.blue_ocean import blue_ocean_score
from radar.scoring.classifier import classify_stage, status_for
from radar.scoring.metrics import compute_metrics
from radar.scoring.velocity import velocity_score

NOW = datetime(2026, 10, 3, 12)


@dataclass
class A:
    fingerprint: str
    start_date: datetime | None
    display_format: str = "VIDEO"
    link_url: str = "https://pay.kiwify.com.br/x"
    hook: str | None = None


def emerging_ads():
    ads = []
    for i in range(14):   # 14 criativos novos em 14 dias, em dias diferentes
        ads.append(A(f"n{i}", NOW - timedelta(days=i), "VIDEO" if i % 2 else "IMAGE", hook=f"hook {i}"))
    for i in range(6):    # 6 antigos sobrevivendo
        ads.append(A(f"o{i}", NOW - timedelta(days=45 + i), hook=f"antigo {i % 3}"))
    ads.append(A("n0", NOW - timedelta(days=0)))  # duplicação técnica
    return ads


def test_metrics_counts():
    m = compute_metrics(emerging_ads(), NOW)
    assert m.observed_ads == 21 and m.distinct_creatives == 20
    assert m.new_7d == 8 and m.new_14d == 14 and m.old_active == 6
    assert m.upload_days_14d >= 13 and m.top_url_share == 1.0
    assert dict(m.retro_curve)[0] == 20


def test_velocity_emerging_beats_test_and_confidence_separate():
    m = compute_metrics(emerging_ads(), NOW)
    acc = analyze_retro(m.retro_curve, NOW)
    v1 = velocity_score(m, acc, coverage=1.0, n_snapshots=1, verification="VERIFIED")
    small = compute_metrics([A("x", NOW - timedelta(days=60))], NOW)
    v2 = velocity_score(small, analyze_retro(small.retro_curve, NOW), coverage=1.0, n_snapshots=1,
                        verification="VERIFIED")
    assert v1["score"] > 60 > v2["score"]
    assert v2["score"] <= 25
    # mais histórico => mais confiança
    acc3 = analyze_series([(NOW - timedelta(days=6), 8), (NOW - timedelta(days=3), 14), (NOW, 20)])
    v3 = velocity_score(m, acc3, coverage=1.0, n_snapshots=3, verification="VERIFIED")
    assert v3["confidence"] > v1["confidence"]
    # cobertura parcial derruba confiança
    v4 = velocity_score(m, acc, coverage=0.3, n_snapshots=1, verification="PARTIAL")
    assert v4["confidence"] < v1["confidence"]


def test_stage_classification():
    m = compute_metrics(emerging_ads(), NOW)
    stage, _ = classify_stage(m, analyze_retro(m.retro_curve, NOW), 21)
    assert stage == "ESCALA_EMERGENTE"
    tiny = compute_metrics([A("x", NOW - timedelta(days=3)), A("y", NOW - timedelta(days=5))], NOW)
    assert classify_stage(tiny, analyze_retro(tiny.retro_curve, NOW), 2)[0] == "TESTE"
    big = compute_metrics([A(f"b{i}", NOW - timedelta(days=100 + i)) for i in range(50)], NOW)
    flat = analyze_series([(NOW - timedelta(days=3), 80), (NOW, 80)])
    assert classify_stage(big, flat, 80)[0] == "ESCALA_MADURA"
    assert status_for("ESCALA_MADURA", flat, 20) == "MATURE"
    assert status_for("TESTE", flat, 10, discarded=True) == "DISCARDED"


def test_blue_ocean_bounds_and_confidence():
    kw = dict(texts=["Seu filho não come e você está cansada? Cardápio com receitas"], product_format="cardapio",
              price=27.9, platform="kiwify", has_promise=True, landing_verified=True, hooks_count=6,
              formats_count=2, video_share=0.5, demand_evidence=3, specific_niche=True)
    blue = blue_ocean_score(cluster_advertisers=2, niche_meta_results=30, **kw)
    red = blue_ocean_score(cluster_advertisers=20, niche_meta_results=5000, **kw)
    unknown = blue_ocean_score(cluster_advertisers=None, niche_meta_results=None, **kw)
    assert 0 <= red["score"] < blue["score"] <= 100
    assert unknown["confidence"] < blue["confidence"]
