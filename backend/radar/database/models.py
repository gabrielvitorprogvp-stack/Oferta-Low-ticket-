"""Modelo de dados do Radar.

Compatível com SQLite (padrão) e PostgreSQL: só tipos portáveis (JSON, DateTime, etc.).
Datas são sempre gravadas em UTC *naive* para evitar diferenças entre dialetos.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


# Estados de verificação de dados (nunca inventar: o que não foi observado não é VERIFIED)
VERIFIED = "VERIFIED"
PARTIAL = "PARTIAL"
NOT_VERIFIED = "NOT_VERIFIED"
BLOCKED = "BLOCKED"

# Status de acompanhamento (watchlist)
STATUSES = ("NEW", "WATCHING", "TESTING", "EMERGING", "MATURE", "DECLINING", "DISCARDED")

# Estágios de escala
STAGE_TEST = "TESTE"
STAGE_EMERGING = "ESCALA_EMERGENTE"
STAGE_MATURE = "ESCALA_MADURA"
STAGE_UNKNOWN = "INDEFINIDO"


class MarketCluster(Base):
    __tablename__ = "market_clusters"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    advertisers_count: Mapped[int] = mapped_column(Integer, default=0)
    offers_count: Mapped[int] = mapped_column(Integer, default=0)
    emerging_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_velocity: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Advertiser(Base):
    __tablename__ = "advertisers"
    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(300), default="")
    page_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    page_categories: Mapped[list] = mapped_column(JSON, default=list)
    page_like_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    niche: Mapped[str | None] = mapped_column(String(120), nullable=True)
    cluster_id: Mapped[int | None] = mapped_column(ForeignKey("market_clusters.id"), nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="NEW", index=True)
    meta_status: Mapped[str] = mapped_column(String(20), default=NOT_VERIFIED)
    pending_meta: Mapped[bool] = mapped_column(Boolean, default=True)  # precisa (re)analisar na Meta
    discard_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    discovered_via: Mapped[str | None] = mapped_column(String(300), nullable=True)

    # métricas mais recentes (cache do último snapshot)
    active_ads: Mapped[int | None] = mapped_column(Integer, nullable=True)
    distinct_creatives: Mapped[int | None] = mapped_column(Integer, nullable=True)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    offers: Mapped[list["Offer"]] = relationship(back_populates="advertiser")
    snapshots: Mapped[list["AdSnapshot"]] = relationship(back_populates="advertiser",
                                                         order_by="AdSnapshot.taken_at")


class Offer(Base):
    __tablename__ = "offers"
    __table_args__ = (UniqueConstraint("advertiser_id", "normalized_url"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    advertiser_id: Mapped[int] = mapped_column(ForeignKey("advertisers.id"), index=True)
    name: Mapped[str] = mapped_column(String(300), default="")
    normalized_url: Mapped[str] = mapped_column(String(500))
    landing_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    domain: Mapped[str | None] = mapped_column(String(200), nullable=True)
    checkout_platform: Mapped[str | None] = mapped_column(String(40), nullable=True)

    price_brl: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_old_brl: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_source: Mapped[str | None] = mapped_column(String(40), nullable=True)  # ad|landing|checkout
    product_format: Mapped[str | None] = mapped_column(String(60), nullable=True)
    niche: Mapped[str | None] = mapped_column(String(120), nullable=True)
    cluster_id: Mapped[int | None] = mapped_column(ForeignKey("market_clusters.id"), nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="NEW", index=True)
    stage: Mapped[str] = mapped_column(String(30), default=STAGE_UNKNOWN)
    verification: Mapped[str] = mapped_column(String(20), default=NOT_VERIFIED)
    validation: Mapped[dict] = mapped_column(JSON, default=dict)
    discard_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_locked: Mapped[bool] = mapped_column(Boolean, default=False)  # usuário fixou o status

    velocity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    velocity_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    blue_ocean_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    blue_ocean_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    acceleration: Mapped[dict] = mapped_column(JSON, default=dict)
    modeling: Mapped[dict] = mapped_column(JSON, default=dict)
    history: Mapped[list] = mapped_column(JSON, default=list)  # [[iso, status, motivo], ...]
    demand_status: Mapped[str] = mapped_column(String(20), default=NOT_VERIFIED)
    demand_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_analyzed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    advertiser: Mapped[Advertiser] = relationship(back_populates="offers")
    ads: Mapped[list["Ad"]] = relationship(back_populates="offer")
    landing_pages: Mapped[list["LandingPage"]] = relationship(back_populates="offer",
                                                              order_by="LandingPage.fetched_at")


class Ad(Base):
    __tablename__ = "ads"
    id: Mapped[int] = mapped_column(primary_key=True)
    ad_archive_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    advertiser_id: Mapped[int] = mapped_column(ForeignKey("advertisers.id"), index=True)
    offer_id: Mapped[int | None] = mapped_column(ForeignKey("offers.id"), nullable=True, index=True)
    collation_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    collation_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)  # identifica criativo real
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    start_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    end_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    display_format: Mapped[str | None] = mapped_column(String(30), nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    hook: Mapped[str | None] = mapped_column(Text, nullable=True)
    link_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    link_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    caption: Mapped[str | None] = mapped_column(String(300), nullable=True)
    cta_text: Mapped[str | None] = mapped_column(String(80), nullable=True)
    cta_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    media: Mapped[list] = mapped_column(JSON, default=list)
    publisher_platforms: Mapped[list] = mapped_column(JSON, default=list)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    offer: Mapped[Offer | None] = relationship(back_populates="ads")


class AdSnapshot(Base):
    """Foto do comportamento publicitário de um anunciante (offer_id nulo) ou oferta."""
    __tablename__ = "ad_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    advertiser_id: Mapped[int] = mapped_column(ForeignKey("advertisers.id"), index=True)
    offer_id: Mapped[int | None] = mapped_column(ForeignKey("offers.id"), nullable=True, index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("research_runs.id"), nullable=True)
    taken_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    active_ads_total: Mapped[int | None] = mapped_column(Integer, nullable=True)  # reportado pela Meta
    observed_ads: Mapped[int] = mapped_column(Integer, default=0)
    distinct_creatives: Mapped[int] = mapped_column(Integer, default=0)
    new_7d: Mapped[int] = mapped_column(Integer, default=0)
    new_14d: Mapped[int] = mapped_column(Integer, default=0)
    new_30d: Mapped[int] = mapped_column(Integer, default=0)
    new_40d: Mapped[int] = mapped_column(Integer, default=0)
    old_active: Mapped[int] = mapped_column(Integer, default=0)
    hooks_count: Mapped[int] = mapped_column(Integer, default=0)
    formats: Mapped[dict] = mapped_column(JSON, default=dict)
    coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    verification: Mapped[str] = mapped_column(String(20), default=NOT_VERIFIED)

    advertiser: Mapped[Advertiser] = relationship(back_populates="snapshots")


class LandingPage(Base):
    __tablename__ = "landing_pages"
    id: Mapped[int] = mapped_column(primary_key=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id"), index=True)
    url: Mapped[str] = mapped_column(String(1000))
    final_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    status: Mapped[str] = mapped_column(String(20), default=NOT_VERIFIED)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)  # headline, promessa, preço, bônus...
    screenshot_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    text_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    offer: Mapped[Offer] = relationship(back_populates="landing_pages")


class DemandEvidence(Base):
    __tablename__ = "demand_evidence"
    id: Mapped[int] = mapped_column(primary_key=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id"), index=True)
    source: Mapped[str] = mapped_column(String(40))
    query: Mapped[str] = mapped_column(String(300))
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str | None] = mapped_column(String(40), nullable=True)  # dor|duvida|concorrente|...
    status: Mapped[str] = mapped_column(String(20), default=VERIFIED)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Keyword(Base):
    __tablename__ = "keywords"
    id: Mapped[int] = mapped_column(primary_key=True)
    term: Mapped[str] = mapped_column(String(200), unique=True)
    source: Mapped[str] = mapped_column(String(30), default="seed")  # seed|price|platform|expansion
    origin_offer_id: Mapped[int | None] = mapped_column(ForeignKey("offers.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|explored|failed
    priority: Mapped[float] = mapped_column(Float, default=1.0)
    times_queried: Mapped[int] = mapped_column(Integer, default=0)
    results_last: Mapped[int | None] = mapped_column(Integer, nullable=True)
    candidates_found: Mapped[int] = mapped_column(Integer, default=0)
    last_queried_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ResearchRun(Base):
    __tablename__ = "research_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    trigger: Mapped[str] = mapped_column(String(20), default="manual")
    status: Mapped[str] = mapped_column(String(20), default="running", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    meta_status: Mapped[str] = mapped_column(String(20), default=NOT_VERIFIED)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class RunLog(Base):
    __tablename__ = "run_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("research_runs.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    level: Mapped[str] = mapped_column(String(10), default="INFO")
    stage: Mapped[str] = mapped_column(String(30), default="")
    message: Mapped[str] = mapped_column(Text)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(40))  # EMERGING_SCALE | ACCELERATION | INTERVENTION_REQUIRED
    severity: Mapped[str] = mapped_column(String(10), default="info")
    offer_id: Mapped[int | None] = mapped_column(ForeignKey("offers.id"), nullable=True)
    advertiser_id: Mapped[int | None] = mapped_column(ForeignKey("advertisers.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(300))
    message: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sent_channels: Mapped[list] = mapped_column(JSON, default=list)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
