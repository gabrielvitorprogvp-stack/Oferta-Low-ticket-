"""Simula 3 rodadas da Meta (8 → 17 → 28 criativos) e verifica memória histórica,
detector de aceleração, status EMERGING e alertas — sem navegador."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from radar.crawler.meta_ads import MetaResult
from radar.crawler.meta_parser import parse_search_blobs
from radar.database.models import AdSnapshot, Advertiser, Alert, Offer
from radar.database.session import session_scope
from tests.factories import collated, ssr_blob

T0 = datetime(2026, 9, 25, 12)


def make_ads(n, now):
    res = []
    for i in range(n):
        start = (now - timedelta(days=(i % 12))).replace(tzinfo=timezone.utc)
        if i < 4:
            start = (now - timedelta(days=50 + i)).replace(tzinfo=timezone.utc)  # antigos sobrevivendo
        res.append(collated(1000 + i, start=start, body=f"Hook {i}: seu filho não come? Cardápio infantil "
                                                           f"por apenas R$ 27,90", media_id=str(5000 + i),
                            fmt="VIDEO" if i % 3 else "IMAGE"))
    return parse_search_blobs([ssr_blob(res)]).ads


class FakeMeta:
    def __init__(self):
        self.n, self.now = 8, T0
        self.blocked_reason = self.throttled_reason = None

    available = True

    def search_keyword(self, term):
        ads = make_ads(self.n, self.now)[:3]
        return MetaResult("VERIFIED", term, 500, ads)

    def search_page(self, page_id):
        ads = make_ads(self.n, self.now)
        return MetaResult("VERIFIED", page_id, len(ads), ads)


def run_once(meta, now):
    from radar.pipeline import Pipeline
    p = Pipeline(max_queries=2, skip_external=True, skip_landing=True)
    p.now, p.meta = now, meta
    p._seed_keywords()
    cands = p.discover()
    p.triage_candidates(cands)
    p.analyze_advertisers()
    p.expand_keywords()
    p.score_and_alert()
    p.update_clusters()
    return p


def test_three_runs_detect_emerging_acceleration(tmp_db):
    meta = FakeMeta()
    for n, day in ((8, 0), (17, 3), (28, 6)):
        meta.n, meta.now = n, T0 + timedelta(days=day)
        p = run_once(meta, meta.now)
        assert p.stats["advertisers_analyzed"] == 1

    with session_scope() as s:
        adv = s.scalar(select(Advertiser))
        snaps = s.scalars(select(AdSnapshot).where(AdSnapshot.offer_id.is_(None))
                          .order_by(AdSnapshot.taken_at)).all()
        assert [x.distinct_creatives for x in snaps] == [8, 17, 28]
        o = s.scalar(select(Offer))
        assert o.acceleration["signal"] == "FORTISSIMA" and not o.acceleration["estimated"]
        assert o.status == "EMERGING" and o.stage == "ESCALA_EMERGENTE"
        assert o.velocity_score >= 55 and o.velocity_confidence > 50
        assert o.price_brl == 27.9 and o.checkout_platform == "kiwify"
        assert adv.status == "EMERGING"
        types = {a.type for a in s.scalars(select(Alert))}
        assert "ACCELERATION" in types and "EMERGING_SCALE" in types
        msg = s.scalar(select(Alert).where(Alert.type == "EMERGING_SCALE")).message
        assert "ALERTA DE ESCALA EMERGENTE" in msg and "R$ 27,90" in msg


def test_meta_down_keeps_candidates_pending(tmp_db):
    class DownMeta(FakeMeta):
        available = False
    p = run_once(DownMeta(), T0)
    assert p.stats["queries_skipped_meta_down"] == 2 and p.stats["advertisers_analyzed"] == 0


def test_lock_prevents_parallel_runs(tmp_db):
    from radar.scheduler.lock import RunLock, is_running
    a = RunLock()
    assert a.acquire() and is_running()
    assert not RunLock().acquire()
    a.release()
    assert not is_running()
