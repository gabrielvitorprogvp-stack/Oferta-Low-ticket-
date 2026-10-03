from datetime import datetime, timedelta

from radar.scoring.acceleration import analyze_retro, analyze_series, best_acceleration

T0 = datetime(2026, 10, 1, 9)


def series(*pairs):
    return [(T0 + timedelta(days=d), c) for d, c in pairs]


def test_spec_examples():
    assert analyze_series(series((0, 12), (3, 18))).signal == "FORTE"          # 12→18 em 3 dias
    assert analyze_series(series((0, 18), (7, 19))).signal == "FRACA"          # 18→19 em 7 dias
    assert analyze_series(series((0, 80), (3, 80))).signal == "ESTAVEL"        # 80→80
    assert analyze_series(series((0, 8), (3, 17), (6, 28))).signal == "FORTISSIMA"  # 8→17→28


def test_decline_and_no_data():
    assert analyze_series(series((0, 30), (4, 18))).signal == "QUEDA"
    acc = analyze_series(series((0, 10)))
    assert acc.signal == "SEM_DADOS" and acc.estimated


def test_deltas_and_growth_rate():
    acc = analyze_series(series((0, 8), (3, 12), (7, 17), (10, 28)))
    assert acc.delta_3d == 11 and acc.delta_7d == 16 and not acc.estimated
    assert acc.creative_growth_rate > 0


def test_snapshots_closer_than_10h_are_merged():
    s = [(T0, 10), (T0 + timedelta(hours=2), 11), (T0 + timedelta(days=3), 18)]
    acc = analyze_series(s)
    assert len(acc.series) == 2


def test_retro_estimate_is_capped_and_flagged():
    now = T0
    acc = analyze_retro([[40, 2], [30, 3], [21, 4], [14, 5], [7, 12], [3, 18], [0, 28]], now)
    assert acc.estimated and acc.signal == "FORTE"   # nunca FORTISSIMA sem histórico real
    assert acc.delta_7d == 16
    real = best_acceleration(series((0, 8), (3, 17), (6, 28)), [], now)
    assert real.signal == "FORTISSIMA" and not real.estimated
