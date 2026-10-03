"""Exporta o estado do radar em documentos JSON para o banco do artifact (app no claude.ai).

Gera <out>/offers/o<id>.json (uma oferta com detalhe) e <out>/radar/summary.json.
Os arquivos são enviados com a ferramenta ArtifactData (set por arquivo).
"""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from radar.api.app import alert_row, get_offer, keyword_rows, run_row, stats
from radar.config import get_settings
from radar.database.models import Alert, MarketCluster, Offer, ResearchRun
from radar.database.session import init_db, session_scope

MAX_ADS = 40


def _slim_offer(d: dict) -> dict:
    d = dict(d)
    d["ads"] = [{k: a[k] for k in ("ad_archive_id", "is_active", "start_date", "display_format", "hook",
                                   "body", "cta_text", "fingerprint", "collation_count", "library_url")}
                | {"body": (a["body"] or "")[:400]} for a in d["ads"][:MAX_ADS]]
    for lp in d["landing_pages"]:
        lp.pop("screenshot", None)  # arquivos locais não existem no app
    d["landing_pages"] = d["landing_pages"][:2]
    d["competitors"] = [{k: c[k] for k in ("id", "name", "advertiser", "price_brl", "creatives",
                                           "velocity_score", "status")} for c in d["competitors"]]
    d["demand"] = d["demand"][:20]
    return d


def export_artifact(out: str | None = None) -> Path:
    init_db()
    base = Path(out) if out else get_settings().data_dir / "artifact_export"
    (base / "offers").mkdir(parents=True, exist_ok=True)
    (base / "radar").mkdir(parents=True, exist_ok=True)
    dump = lambda obj, p: p.write_text(json.dumps(obj, default=str, ensure_ascii=False))  # noqa: E731
    with session_scope() as s:
        ids = list(s.scalars(select(Offer.id)))
        for oid in ids:
            dump(_slim_offer(get_offer(oid, s)), base / "offers" / f"o{oid}.json")
        summary = {
            "stats": stats(s),
            "alerts": [alert_row(a) for a in s.scalars(select(Alert).order_by(Alert.created_at.desc()).limit(20))],
            "runs": [run_row(r) for r in s.scalars(select(ResearchRun).order_by(ResearchRun.id.desc()).limit(15))],
            "clusters": [{"name": c.name, "keywords": c.keywords[:6], "advertisers": c.advertisers_count,
                          "offers": c.offers_count, "emerging": c.emerging_count, "avg_velocity": c.avg_velocity}
                         for c in s.scalars(select(MarketCluster))],
            "keywords": keyword_rows(s, 60),
        }
        dump(summary, base / "radar" / "summary.json")
    return base
