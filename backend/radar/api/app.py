"""API do Radar + servidor do dashboard (build estático em dashboard/dist)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from radar.config import BASE_DIR, get_settings
from radar.database.models import (STATUSES, Ad, AdSnapshot, Advertiser, Alert, DemandEvidence, Keyword,
                                   MarketCluster, Offer, ResearchRun, RunLog, utcnow)
from radar.database.session import get_session, init_db
from radar.logging_setup import setup_logging
from radar.scheduler.jobs import build_scheduler, resolve_cron, spawn_run
from radar.scheduler.lock import is_running

log = logging.getLogger("radar.api")
DIST = BASE_DIR.parent / "dashboard" / "dist"


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging()
    init_db()
    sched, cron = build_scheduler()
    if cron:
        sched.start()
    yield
    if cron:
        sched.shutdown(wait=False)


app = FastAPI(title="Radar Low Ticket — Escala Emergente", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/media", StaticFiles(directory=str(get_settings().screenshots_dir)), name="media")


# ---------------------------------------------------------------- serialização
def offer_row(o: Offer, prev7: int | None = None, prev14: int | None = None) -> dict:
    m = o.metrics or {}
    acc = o.acceleration or {}
    return {
        "id": o.id, "name": o.name, "advertiser": o.advertiser.name if o.advertiser else None,
        "advertiser_id": o.advertiser_id, "niche": o.niche, "price_brl": o.price_brl,
        "price_source": o.price_source, "product_format": o.product_format,
        "checkout_platform": o.checkout_platform, "landing_url": o.landing_url, "domain": o.domain,
        "creatives": m.get("distinct_creatives"), "active_ads": m.get("observed_ads"),
        "new_7d": m.get("new_7d"), "new_14d": m.get("new_14d"), "old_active": m.get("old_active"),
        "delta_7d": acc.get("delta_7d"), "delta_14d": acc.get("delta_14d"),
        "acceleration": acc.get("signal"), "acceleration_estimated": acc.get("estimated", True),
        "velocity_score": o.velocity_score, "velocity_confidence": o.velocity_confidence,
        "blue_ocean_score": o.blue_ocean_score, "blue_ocean_confidence": o.blue_ocean_confidence,
        "status": o.status, "stage": o.stage, "verification": o.verification,
        "status_locked": o.status_locked, "discard_reason": o.discard_reason,
        "first_seen_at": o.first_seen_at, "last_analyzed_at": o.last_analyzed_at,
    }


FILTERS = {
    "emerging": lambda q: q.where(Offer.status == "EMERGING"),
    "blue_ocean": lambda q: q.where(Offer.blue_ocean_score >= 60, Offer.status != "DISCARDED"),
    "new": lambda q: q.where(Offer.status == "NEW"),
    "watching": lambda q: q.where(Offer.status.in_(("WATCHING", "TESTING"))),
    "mature": lambda q: q.where(Offer.status == "MATURE"),
    "declining": lambda q: q.where(Offer.status == "DECLINING"),
    "discarded": lambda q: q.where(Offer.status == "DISCARDED"),
    "active": lambda q: q.where(Offer.status != "DISCARDED"),
}
SORTS = {"velocity": Offer.velocity_score, "blue_ocean": Offer.blue_ocean_score,
         "recent": Offer.last_analyzed_at, "price": Offer.price_brl, "first_seen": Offer.first_seen_at}


# ---------------------------------------------------------------- endpoints
@app.get("/api/health")
def health():
    return {"ok": True, "running": is_running()}


@app.get("/api/stats")
def stats(s: Session = Depends(get_session)):
    today = utcnow() - timedelta(hours=24)
    count = lambda q: s.scalar(q) or 0  # noqa: E731
    last_run = s.scalar(select(ResearchRun).order_by(ResearchRun.id.desc()).limit(1))
    return {
        "offers_monitored": count(select(func.count(Offer.id)).where(Offer.status != "DISCARDED")),
        "emerging": count(select(func.count(Offer.id)).where(Offer.status == "EMERGING")),
        "new_today": count(select(func.count(Offer.id)).where(Offer.first_seen_at >= today,
                                                               Offer.status != "DISCARDED")),
        "advertisers_monitored": count(select(func.count(Advertiser.id))
                                       .where(Advertiser.status != "DISCARDED")),
        "alerts_recent": count(select(func.count(Alert.id)).where(Alert.created_at >= today)),
        "blue_ocean": count(select(func.count(Offer.id)).where(Offer.blue_ocean_score >= 60,
                                                               Offer.status != "DISCARDED")),
        "discarded": count(select(func.count(Offer.id)).where(Offer.status == "DISCARDED")),
        "keywords": count(select(func.count(Keyword.id))),
        "by_status": dict(s.execute(select(Offer.status, func.count(Offer.id)).group_by(Offer.status)).all()),
        "running": is_running(),
        "schedule": get_settings().radar_schedule,
        "last_run": run_row(last_run) if last_run else None,
    }


@app.get("/api/offers")
def list_offers(filter: str = "active", q: str | None = None, sort: str = "velocity",
                niche: str | None = None, limit: int = Query(200, le=1000), offset: int = 0,
                s: Session = Depends(get_session)):
    stmt = select(Offer).join(Advertiser)
    if filter in FILTERS:
        stmt = FILTERS[filter](stmt)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Offer.name.ilike(like), Advertiser.name.ilike(like), Offer.niche.ilike(like),
                              Offer.domain.ilike(like)))
    if niche:
        stmt = stmt.where(Offer.niche == niche)
    col = SORTS.get(sort, Offer.velocity_score)
    total = s.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = s.scalars(stmt.order_by(col.desc().nulls_last()).offset(offset).limit(limit)).all()
    return {"total": total, "items": [offer_row(o) for o in rows]}


@app.get("/api/offers/{oid}")
def get_offer(oid: int, s: Session = Depends(get_session)):
    o = s.get(Offer, oid)
    if not o:
        raise HTTPException(404)
    snaps = s.scalars(select(AdSnapshot).where(AdSnapshot.offer_id == oid).order_by(AdSnapshot.taken_at)).all()
    adv_snaps = s.scalars(select(AdSnapshot).where(AdSnapshot.advertiser_id == o.advertiser_id,
                                                   AdSnapshot.offer_id.is_(None))
                          .order_by(AdSnapshot.taken_at)).all()
    ads = s.scalars(select(Ad).where(Ad.offer_id == oid).order_by(Ad.start_date.desc().nulls_last())).all()
    lps = o.landing_pages
    demand = s.scalars(select(DemandEvidence).where(DemandEvidence.offer_id == oid)).all()
    competitors = []
    if o.niche:
        competitors = [offer_row(c) for c in s.scalars(
            select(Offer).where(Offer.niche == o.niche, Offer.id != oid, Offer.status != "DISCARDED")
            .order_by(Offer.velocity_score.desc().nulls_last()).limit(12))]
    # timeline de lançamento de criativos (por data de início, 1 ponto por criativo)
    first_by_fp: dict[str, object] = {}
    for a in ads:
        if a.start_date and (a.fingerprint not in first_by_fp or a.start_date < first_by_fp[a.fingerprint]):
            first_by_fp[a.fingerprint] = a.start_date
    launches: dict[str, int] = {}
    for d in first_by_fp.values():
        k = d.date().isoformat()
        launches[k] = launches.get(k, 0) + 1
    alerts = s.scalars(select(Alert).where(Alert.offer_id == oid).order_by(Alert.created_at.desc())).all()
    return {
        **offer_row(o),
        "metrics": o.metrics, "acceleration_detail": o.acceleration, "score_breakdown": o.score_breakdown,
        "validation": o.validation, "modeling": o.modeling, "history": o.history,
        "demand_status": o.demand_status, "normalized_url": o.normalized_url,
        "advertiser_detail": adv_row(o.advertiser),
        "snapshots": [snap_row(x) for x in snaps],
        "advertiser_snapshots": [snap_row(x) for x in adv_snaps],
        "launch_timeline": sorted(launches.items()),
        "ads": [ad_row(a) for a in ads[:300]],
        "landing_pages": [{"id": lp.id, "url": lp.url, "final_url": lp.final_url, "status": lp.status,
                           "fetched_at": lp.fetched_at, "title": lp.title, "data": lp.data,
                           "screenshot": f"/media/{lp.screenshot_path}" if lp.screenshot_path else None,
                           "error": lp.error} for lp in reversed(lps)],
        "demand": [{"source": d.source, "query": d.query, "url": d.url, "title": d.title,
                    "snippet": d.snippet, "kind": d.kind, "fetched_at": d.fetched_at} for d in demand],
        "competitors": competitors,
        "alerts": [alert_row(a) for a in alerts],
    }


class OfferPatch(BaseModel):
    status: str | None = None
    locked: bool | None = None


@app.patch("/api/offers/{oid}")
def patch_offer(oid: int, body: OfferPatch, s: Session = Depends(get_session)):
    o = s.get(Offer, oid)
    if not o:
        raise HTTPException(404)
    if body.status:
        if body.status not in STATUSES:
            raise HTTPException(400, f"status inválido; use {STATUSES}")
        o.status = body.status
        o.history = (o.history or []) + [[utcnow().isoformat(), body.status, "alterado manualmente"]]
        o.status_locked = True if body.locked is None else body.locked
    elif body.locked is not None:
        o.status_locked = body.locked
    s.commit()
    return offer_row(o)


def adv_row(a: Advertiser | None) -> dict | None:
    if not a:
        return None
    return {"id": a.id, "page_id": a.page_id, "name": a.name, "page_url": a.page_url,
            "library_url": f"https://www.facebook.com/ads/library/?active_status=active&ad_type=all"
                           f"&country={get_settings().meta_country}&view_all_page_id={a.page_id}",
            "categories": a.page_categories, "likes": a.page_like_count, "status": a.status,
            "meta_status": a.meta_status, "active_ads": a.active_ads,
            "distinct_creatives": a.distinct_creatives, "niche": a.niche,
            "discovered_via": a.discovered_via, "first_seen_at": a.first_seen_at,
            "last_checked_at": a.last_checked_at, "next_check_at": a.next_check_at,
            "discard_reason": a.discard_reason}


def snap_row(x: AdSnapshot) -> dict:
    return {"taken_at": x.taken_at, "active_ads_total": x.active_ads_total, "observed_ads": x.observed_ads,
            "distinct_creatives": x.distinct_creatives, "new_7d": x.new_7d, "new_14d": x.new_14d,
            "new_30d": x.new_30d, "new_40d": x.new_40d, "old_active": x.old_active,
            "hooks_count": x.hooks_count, "formats": x.formats, "coverage": x.coverage,
            "verification": x.verification}


def ad_row(a: Ad) -> dict:
    return {"id": a.id, "ad_archive_id": a.ad_archive_id, "is_active": a.is_active, "start_date": a.start_date,
            "display_format": a.display_format, "hook": a.hook, "body": (a.body or "")[:1200],
            "title": a.title, "cta_text": a.cta_text, "link_url": a.link_url, "fingerprint": a.fingerprint[:10],
            "collation_count": a.collation_count, "thumb": (a.media or [None])[0],
            "library_url": f"https://www.facebook.com/ads/library/?id={a.ad_archive_id}",
            "platforms": a.publisher_platforms}


def alert_row(a: Alert) -> dict:
    return {"id": a.id, "type": a.type, "severity": a.severity, "title": a.title, "message": a.message,
            "offer_id": a.offer_id, "advertiser_id": a.advertiser_id, "created_at": a.created_at,
            "sent_channels": a.sent_channels, "read": a.read, "payload": a.payload}


def run_row(r: ResearchRun) -> dict:
    return {"id": r.id, "trigger": r.trigger, "status": r.status, "started_at": r.started_at,
            "finished_at": r.finished_at, "meta_status": r.meta_status, "stats": r.stats,
            "error": (r.error or "")[:2000] or None}


@app.get("/api/advertisers")
def list_advertisers(status: str | None = None, limit: int = 300, s: Session = Depends(get_session)):
    stmt = select(Advertiser)
    if status:
        stmt = stmt.where(Advertiser.status == status)
    rows = s.scalars(stmt.order_by(Advertiser.last_checked_at.desc().nulls_last()).limit(limit)).all()
    return [adv_row(a) for a in rows]


@app.get("/api/advertisers/{aid}")
def get_advertiser(aid: int, s: Session = Depends(get_session)):
    a = s.get(Advertiser, aid)
    if not a:
        raise HTTPException(404)
    snaps = [snap_row(x) for x in a.snapshots if x.offer_id is None]
    return {**adv_row(a), "snapshots": snaps, "offers": [offer_row(o) for o in a.offers]}


@app.get("/api/alerts")
def list_alerts(limit: int = 50, s: Session = Depends(get_session)):
    return [alert_row(a) for a in s.scalars(select(Alert).order_by(Alert.created_at.desc()).limit(limit))]


@app.post("/api/alerts/{aid}/read")
def read_alert(aid: int, s: Session = Depends(get_session)):
    a = s.get(Alert, aid)
    if not a:
        raise HTTPException(404)
    a.read = True
    s.commit()
    return {"ok": True}


@app.get("/api/runs")
def list_runs(limit: int = 30, s: Session = Depends(get_session)):
    return [run_row(r) for r in s.scalars(select(ResearchRun).order_by(ResearchRun.id.desc()).limit(limit))]


@app.get("/api/runs/{rid}/logs")
def run_logs(rid: int, level: str | None = None, s: Session = Depends(get_session)):
    stmt = select(RunLog).where(RunLog.run_id == rid)
    if level:
        stmt = stmt.where(RunLog.level == level)
    return [{"ts": x.ts, "level": x.level, "stage": x.stage, "message": x.message}
            for x in s.scalars(stmt.order_by(RunLog.id))]


class RunRequest(BaseModel):
    max_queries: int | None = None
    max_advertisers: int | None = None
    skip_external: bool = False
    terms: list[str] | None = None


@app.post("/api/runs")
def trigger_run(body: RunRequest | None = None):
    body = body or RunRequest()
    args: list[str] = []
    if body.max_queries:
        args += ["--max-queries", str(body.max_queries)]
    if body.max_advertisers:
        args += ["--max-advertisers", str(body.max_advertisers)]
    if body.skip_external:
        args.append("--skip-external")
    for t in body.terms or []:
        args += ["--term", t]
    if not spawn_run("manual", args):
        raise HTTPException(409, "já existe uma rodada em execução")
    return {"started": True}


@app.get("/api/keywords")
def list_keywords(limit: int = 300, s: Session = Depends(get_session)):
    rows = s.scalars(select(Keyword).order_by(Keyword.candidates_found.desc(), Keyword.priority.desc())
                     .limit(limit)).all()
    return [{"id": k.id, "term": k.term, "source": k.source, "status": k.status, "priority": k.priority,
             "times_queried": k.times_queried, "results_last": k.results_last,
             "candidates_found": k.candidates_found, "last_queried_at": k.last_queried_at} for k in rows]


class KeywordIn(BaseModel):
    term: str


@app.post("/api/keywords")
def add_keyword(body: KeywordIn, s: Session = Depends(get_session)):
    term = body.term.strip()
    if not term:
        raise HTTPException(400)
    if not s.scalar(select(Keyword).where(Keyword.term == term)):
        s.add(Keyword(term=term, source="manual", priority=3.0))
        s.commit()
    return {"ok": True}


@app.get("/api/clusters")
def list_clusters(s: Session = Depends(get_session)):
    rows = s.scalars(select(MarketCluster).order_by(MarketCluster.emerging_count.desc(),
                                                    MarketCluster.avg_velocity.desc().nulls_last())).all()
    return [{"id": c.id, "name": c.name, "keywords": c.keywords, "advertisers": c.advertisers_count,
             "offers": c.offers_count, "emerging": c.emerging_count, "avg_velocity": c.avg_velocity}
            for c in rows]


@app.get("/api/settings")
def settings_view():
    st = get_settings()
    return {"schedule": st.radar_schedule, "cron": resolve_cron(st.radar_schedule),
            "telegram": bool(st.telegram_bot_token and st.telegram_chat_id),
            "search_providers": st.search_providers, "brave_api": bool(st.brave_api_key),
            "country": st.meta_country, "low_ticket_range": [st.low_ticket_min_brl, st.low_ticket_max_brl],
            "database": "postgresql" if st.db_url.startswith("postgres") else "sqlite"}


# ---------------------------------------------------------------- dashboard estático
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(DIST / "assets")), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = DIST / path
        if path and f.is_file() and DIST in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
