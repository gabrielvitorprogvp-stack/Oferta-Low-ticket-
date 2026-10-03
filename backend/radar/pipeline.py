"""Orquestrador de uma rodada de garimpagem.

  A. descoberta     — ≥30 consultas na Meta (sementes + palavras expandidas)
  B. triagem        — é produto digital low ticket com oferta direta?
  C. análise Meta   — anúncios completos do anunciante + snapshot (memória histórica)
  D. landing pages  — estrutura do funil, preço, screenshot
  E. expansão       — novas palavras-chave extraídas das ofertas (SEMENTE→OFERTA→PALAVRAS)
  F. demanda        — Google/Bing/DDG/Brave/Reddit para os candidatos fortes
  G. scoring        — velocity, mar azul, aceleração, estágio, status, alertas

Cada etapa é isolada: falha em uma fonte nunca encerra a rodada.
"""
from __future__ import annotations

import logging
import re
import traceback
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from radar.config import get_settings
from radar.crawler.meta_parser import ParsedAd
from radar.database.models import (BLOCKED, NOT_VERIFIED, PARTIAL, STAGE_EMERGING, VERIFIED, Ad,
                                   AdSnapshot, Advertiser, Alert, DemandEvidence, Keyword, LandingPage,
                                   MarketCluster, Offer, ResearchRun, RunLog, utcnow)
from radar.database.session import init_db, session_scope
from radar.research.niches import detect_niche
from radar.research.offer_filter import triage
from radar.research.seeds import initial_keywords
from radar.research.text_utils import (detect_platform, domain_of, extract_keyphrases,
                                       extract_prices_brl, guess_offer_price, norm_text, normalize_url)
from radar.scheduler.lock import RunLock, close_stale_runs
from radar.scoring.acceleration import best_acceleration
from radar.scoring.blue_ocean import blue_ocean_score
from radar.scoring.classifier import classify_stage, status_for
from radar.scoring.metrics import compute_metrics
from radar.scoring.velocity import velocity_score

log = logging.getLogger("radar.pipeline")

NO_FUNNEL_DOMAINS = ("instagram.com", "facebook.com", "fb.me", "m.me", "wa.me", "api.whatsapp.com",
                     "whatsapp.com", "linktr.ee", "tiktok.com", "youtube.com", "youtu.be")
REVISIT = {"EMERGING": timedelta(hours=6), "NEW": timedelta(hours=6), "WATCHING": timedelta(hours=20),
           "TESTING": timedelta(days=3), "DECLINING": timedelta(days=3), "MATURE": timedelta(days=7)}


class StoredAd:
    """Adaptador Ad (ORM) → interface usada pelas métricas."""

    def __init__(self, a: Ad):
        self.fingerprint, self.start_date = a.fingerprint, a.start_date
        self.display_format, self.link_url, self.hook = a.display_format, a.link_url, a.hook
        self.body, self.title = a.body, a.title


class Pipeline:
    def __init__(self, trigger: str = "manual", *, max_queries: int | None = None,
                 max_advertisers: int | None = None, skip_external: bool = False,
                 skip_landing: bool = False, terms: list[str] | None = None):
        self.s = get_settings()
        self.trigger = trigger
        self.max_queries = max_queries
        self.max_advertisers = max_advertisers or self.s.max_advertisers_per_run
        self.skip_external = skip_external
        self.skip_landing = skip_landing
        self.terms = terms
        self.run_id: int | None = None
        self.stats: dict = defaultdict(int)
        self.now = utcnow()
        self.touched_offers: set[int] = set()
        self.bm = None
        self.meta = None
        self.search = None

    # ------------------------------------------------------------------ infra
    def emit(self, level: str, msg: str, stage: str = "") -> None:
        log.log(getattr(logging, level, logging.INFO), "[%s] %s", stage or "-", msg)
        if self.run_id is None:
            return
        try:
            with session_scope() as s:
                s.add(RunLog(run_id=self.run_id, level=level, stage=stage, message=msg[:4000]))
                run = s.get(ResearchRun, self.run_id)
                if run:
                    run.heartbeat_at = utcnow()
                    run.stats = dict(self.stats)
        except Exception:  # noqa: BLE001
            log.exception("falha ao gravar log")

    def _stage(self, name: str, fn) -> None:
        self.emit("INFO", f"iniciando etapa {name}", name)
        try:
            fn()
        except Exception as e:  # noqa: BLE001 — etapa falha, rodada continua
            self.stats["stage_errors"] += 1
            self.emit("ERROR", f"etapa {name} falhou: {e}\n{traceback.format_exc()[-1500:]}", name)

    # ------------------------------------------------------------------ execução
    def execute(self) -> int | None:
        init_db()
        lock = RunLock()
        if not lock.acquire():
            log.warning("já existe uma rodada em execução — ignorando novo disparo")
            return None
        try:
            close_stale_runs()
            with session_scope() as s:
                run = ResearchRun(trigger=self.trigger, status="running")
                s.add(run)
                s.flush()
                self.run_id = run.id
            self.emit("INFO", f"rodada #{self.run_id} iniciada ({self.trigger})", "run")
            status, error = "completed", None
            try:
                from radar.crawler.browser import BrowserManager
                from radar.crawler.meta_ads import MetaAdsClient
                from radar.research.search_providers import MultiSearch
                self.bm = BrowserManager().start()
                self.meta = MetaAdsClient(self.bm, lambda lv, m: self.emit(lv, m, "meta"))
                self.search = MultiSearch(self.bm)
                self._seed_keywords()
                candidates = {}
                self._stage("descoberta", lambda: candidates.update(self.discover()))
                self._stage("triagem", lambda: self.triage_candidates(candidates))
                self._stage("analise_meta", self.analyze_advertisers)
                if not self.skip_landing:
                    self._stage("landing_pages", self.analyze_landings)
                self._stage("expansao", self.expand_keywords)
                if not self.skip_external:
                    self._stage("demanda", self.validate_demand)
                self._stage("scoring", self.score_and_alert)
                self._stage("clusters", self.update_clusters)
                if self.meta.blocked_reason:
                    status = "partial"
                    self._intervention_alert(self.meta.blocked_reason)
                elif self.meta.throttled_reason or self.stats["stage_errors"] or self.stats["meta_failed"]:
                    status = "partial"
            except Exception as e:  # noqa: BLE001
                status, error = "failed", f"{e}\n{traceback.format_exc()[-2000:]}"
                self.emit("ERROR", f"rodada falhou: {e}", "run")
            finally:
                if self.bm:
                    self.bm.close()
            with session_scope() as s:
                run = s.get(ResearchRun, self.run_id)
                run.status, run.error, run.finished_at = status, error, utcnow()
                run.stats = dict(self.stats)
                run.meta_status = (BLOCKED if self.meta and self.meta.blocked_reason else
                                   VERIFIED if self.stats["meta_ok"] and not self.stats["meta_failed"] else
                                   PARTIAL if self.stats["meta_ok"] else NOT_VERIFIED)
            self.emit("INFO", f"rodada #{self.run_id} finalizada: {status} — {dict(self.stats)}", "run")
            return self.run_id
        finally:
            lock.release()

    # ------------------------------------------------------------------ A. descoberta
    def _seed_keywords(self) -> None:
        with session_scope() as s:
            existing = set(s.scalars(select(Keyword.term)))
            for term, src, prio in initial_keywords():
                if term not in existing:
                    s.add(Keyword(term=term, source=src, priority=prio))
            for t in self.terms or []:
                if t not in existing:
                    s.add(Keyword(term=t, source="manual", priority=3.0))

    def _plan_queries(self, s: Session) -> list[Keyword]:
        n = self.max_queries or self.s.discovery_min_queries
        if self.terms:
            return list(s.scalars(select(Keyword).where(Keyword.term.in_(self.terms))))
        pending = list(s.scalars(select(Keyword).where(Keyword.status == "pending")
                                 .order_by(Keyword.priority.desc(), Keyword.created_at).limit(n)))
        # metade das vagas restantes para rotação de termos já explorados (os que mais renderam)
        rest = n - len(pending)
        if rest > 0:
            pending += list(s.scalars(
                select(Keyword).where(Keyword.status != "pending")
                .order_by(Keyword.last_queried_at.asc().nulls_first(),
                          Keyword.candidates_found.desc()).limit(rest)))
        return pending[: self.s.discovery_max_queries]

    def discover(self) -> dict[str, dict]:
        with session_scope() as s:
            plan = [(k.id, k.term) for k in self._plan_queries(s)]
        self.emit("INFO", f"{len(plan)} consultas planejadas", "descoberta")
        candidates: dict[str, dict] = {}
        for kid, term in plan:
            self.stats["queries_tested"] += 1
            if not self.meta.available:
                self.stats["queries_skipped_meta_down"] += 1
                self._external_discovery(term)
                continue
            res = self.meta.search_keyword(term)
            found = 0
            if res.status in (VERIFIED, PARTIAL):
                self.stats["meta_ok"] += 1
                for ad in res.ads:
                    if not ad.page_id:
                        continue
                    c = candidates.setdefault(ad.page_id, {"ads": {}, "queries": set()})
                    c["ads"][ad.ad_archive_id] = ad
                    c["queries"].add(term)
                found = len({a.page_id for a in res.ads if a.page_id})
            else:
                self.stats["queries_failed"] += 1
                self.stats["meta_failed"] += 1
            with session_scope() as s:
                k = s.get(Keyword, kid)
                k.times_queried += 1
                k.last_queried_at = utcnow()
                k.status = "explored" if res.status in (VERIFIED, PARTIAL) else "failed"
                k.results_last = res.total_count
                k.candidates_found += found
            self.emit("INFO", f"'{term}': {res.status}, ~{res.total_count} resultados, "
                              f"{found} anunciantes", "descoberta")
        self.stats["candidates_found"] = len(candidates)
        return candidates

    def _external_discovery(self, term: str) -> None:
        """Meta indisponível: busca páginas de checkout indexadas e extrai novas palavras."""
        if self.skip_external or not self.search or not self.search.usable:
            return
        res = self.search.search(f"site:pay.kiwify.com.br OR site:pay.hotmart.com {term}", n=8)
        titles = [h.title for h in res.hits]
        self.stats["external_queries"] += 1
        if not titles:
            return
        with session_scope() as s:
            for ph in extract_keyphrases(titles, top=4, min_count=1):
                if not s.scalar(select(Keyword).where(Keyword.term == ph)):
                    s.add(Keyword(term=ph, source="external", priority=1.3))
                    self.stats["keywords_from_external"] += 1

    # ------------------------------------------------------------------ B. triagem
    def triage_candidates(self, candidates: dict[str, dict]) -> None:
        for page_id, c in candidates.items():
            ads: list[ParsedAd] = list(c["ads"].values())
            texts = [a.all_text for a in ads]
            links = [a.link_url for a in ads] + [a.caption for a in ads]
            platform = detect_platform(*links)
            prices = [p for a in ads for p in extract_prices_brl(a.all_text)]
            price, _ = guess_offer_price(prices, " ".join(texts))
            has_link = any(a.link_url and not (domain_of(a.link_url) or "").endswith(NO_FUNNEL_DOMAINS)
                           for a in ads)
            tr = triage(texts, page_categories=ads[0].page_categories, platform=platform, price=price,
                        cta_types=[a.cta_type for a in ads if a.cta_type], has_link=has_link,
                        min_price=self.s.low_ticket_min_brl, max_price=self.s.low_ticket_max_brl)
            with session_scope() as s:
                adv = s.scalar(select(Advertiser).where(Advertiser.page_id == page_id))
                is_new = adv is None
                if is_new:
                    adv = Advertiser(page_id=page_id, discovered_via=", ".join(sorted(c["queries"]))[:300])
                    s.add(adv)
                adv.name = ads[0].page_name or adv.name
                adv.page_url = ads[0].page_url or adv.page_url
                adv.page_categories = ads[0].page_categories or adv.page_categories
                adv.page_like_count = ads[0].page_like_count or adv.page_like_count
                if not tr.accepted:
                    if is_new:
                        adv.status, adv.discard_reason, adv.pending_meta = "DISCARDED", tr.discard_reason, False
                        self.stats["candidates_discarded"] += 1
                    continue
                self.stats["candidates_accepted"] += 1
                if is_new:
                    adv.status, adv.pending_meta = "NEW", True
                    # prioridade na fila: quantos anúncios dele apareceram + quão recentes
                    recent = sum(1 for a in ads if a.start_date and (self.now - a.start_date).days <= 14)
                    adv.next_check_at = self.now - timedelta(minutes=len(ads) + 2 * recent)
        self.emit("INFO", f"triagem: {self.stats['candidates_accepted']} aceitos, "
                          f"{self.stats['candidates_discarded']} descartados", "triagem")

    # ------------------------------------------------------------------ C. análise Meta
    def _advertiser_queue(self, s: Session) -> list[int]:
        due = list(s.scalars(
            select(Advertiser).where(Advertiser.status != "DISCARDED")
            .where((Advertiser.pending_meta.is_(True)) | (Advertiser.next_check_at <= self.now)
                   | (Advertiser.next_check_at.is_(None)))))
        order = {"EMERGING": 0, "NEW": 1, "WATCHING": 2, "DECLINING": 3, "TESTING": 4, "MATURE": 5}
        due.sort(key=lambda a: (order.get(a.status, 9), a.next_check_at or datetime.min))
        emerging = [a.id for a in due if a.status == "EMERGING"]
        others = [a.id for a in due if a.status != "EMERGING"]
        return emerging + others[: max(0, self.max_advertisers - len(emerging))]

    def analyze_advertisers(self) -> None:
        with session_scope() as s:
            queue = self._advertiser_queue(s)
        self.emit("INFO", f"{len(queue)} anunciantes na fila de análise Meta", "analise_meta")
        for adv_id in queue:
            if not self.meta.available:
                self.emit("WARNING", "Meta indisponível — anunciantes restantes ficam pendentes "
                                     "para a próxima rodada", "analise_meta")
                break
            with session_scope() as s:
                adv = s.get(Advertiser, adv_id)
                page_id, name = adv.page_id, adv.name
            res = self.meta.search_page(page_id)
            if res.status in (BLOCKED, NOT_VERIFIED):
                self.stats["meta_failed"] += 1
                with session_scope() as s:
                    adv = s.get(Advertiser, adv_id)
                    adv.pending_meta, adv.meta_status = True, res.status
                continue
            self.stats["meta_ok"] += 1
            self.stats["advertisers_analyzed"] += 1
            self.stats["meta_" + res.status.lower()] += 1
            self._store_advertiser_ads(adv_id, res)
            self.emit("INFO", f"{name}: {res.status}, {len(res.ads)}/{res.total_count} anúncios "
                              f"(cobertura {res.coverage})", "analise_meta")

    def _store_advertiser_ads(self, adv_id: int, res) -> None:
        with session_scope() as s:
            adv = s.get(Advertiser, adv_id)
            seen_ids = set()
            offers_by_url: dict[str, Offer] = {o.normalized_url: o for o in adv.offers}
            for pa in res.ads:
                seen_ids.add(pa.ad_archive_id)
                if pa.page_name:
                    adv.name = pa.page_name
                    adv.page_categories = pa.page_categories or adv.page_categories
                    adv.page_like_count = pa.page_like_count or adv.page_like_count
                    adv.page_url = pa.page_url or adv.page_url
                key = normalize_url(pa.link_url) or "__sem_link__"
                offer = offers_by_url.get(key)
                if offer is None:
                    offer = Offer(advertiser_id=adv.id, normalized_url=key, landing_url=pa.link_url,
                                  domain=domain_of(pa.link_url), name=_offer_name(pa, key))
                    s.add(offer)
                    s.flush()
                    offers_by_url[key] = offer
                    self.stats["new_offers"] += 1
                ad = s.scalar(select(Ad).where(Ad.ad_archive_id == pa.ad_archive_id))
                if ad is None:
                    ad = Ad(ad_archive_id=pa.ad_archive_id, advertiser_id=adv.id, fingerprint=pa.fingerprint)
                    s.add(ad)
                    self.stats["new_ads"] += 1
                ad.offer_id = offer.id
                ad.collation_id, ad.collation_count = pa.collation_id, pa.collation_count
                ad.fingerprint, ad.is_active = pa.fingerprint, pa.is_active
                ad.start_date, ad.end_date = pa.start_date, pa.end_date
                ad.display_format, ad.body, ad.title, ad.hook = pa.display_format, pa.body, pa.title, pa.hook
                ad.link_url, ad.link_description, ad.caption = pa.link_url, pa.link_description, pa.caption
                ad.cta_text, ad.cta_type = pa.cta_text, pa.cta_type
                ad.media, ad.publisher_platforms = pa.media[:6], pa.publisher_platforms
                ad.last_seen_at = utcnow()
                self.touched_offers.add(offer.id)
            s.flush()
            if res.status == VERIFIED:
                # cobertura completa: o que não apareceu deixou de estar ativo
                for ad in s.scalars(select(Ad).where(Ad.advertiser_id == adv.id, Ad.is_active.is_(True))):
                    if ad.ad_archive_id not in seen_ids:
                        ad.is_active = False
                        if ad.offer_id:
                            self.touched_offers.add(ad.offer_id)

            active = [StoredAd(a) for a in s.scalars(
                select(Ad).where(Ad.advertiser_id == adv.id, Ad.ad_archive_id.in_(seen_ids)))]
            m = compute_metrics(active, self.now)
            s.add(_snapshot(adv.id, None, self.run_id, res, m, taken_at=self.now))
            adv.active_ads, adv.distinct_creatives = res.total_count, m.distinct_creatives
            adv.meta_status, adv.pending_meta, adv.last_checked_at = res.status, False, self.now
            for offer in offers_by_url.values():
                oads = [StoredAd(a) for a in s.scalars(
                    select(Ad).where(Ad.offer_id == offer.id, Ad.ad_archive_id.in_(seen_ids)))]
                if not oads:
                    continue
                om = compute_metrics(oads, self.now)
                s.add(_snapshot(adv.id, offer.id, self.run_id, res, om, offer_total=len(oads),
                                taken_at=self.now))

    # ------------------------------------------------------------------ D. landing pages
    def analyze_landings(self) -> None:
        from radar.crawler.landing_page import analyze_landing
        with session_scope() as s:
            q = (select(Offer).join(Advertiser)
                 .where(Offer.status != "DISCARDED", Advertiser.status != "DISCARDED",
                        Offer.normalized_url != "__sem_link__"))
            offers = list(s.scalars(q))
            recent_cut = self.now - timedelta(days=3)
            todo = []
            for o in offers:
                if (o.domain or "").endswith(NO_FUNNEL_DOMAINS):
                    continue
                last = o.landing_pages[-1] if o.landing_pages else None
                if last and last.fetched_at > recent_cut and last.status in (VERIFIED, PARTIAL):
                    continue
                n_ads = s.scalar(select(func.count(Ad.id)).where(Ad.offer_id == o.id, Ad.is_active.is_(True)))
                if n_ads:
                    todo.append((n_ads, o.id, o.landing_url))
        todo.sort(reverse=True)
        for _, oid, url in todo[: self.s.max_landing_pages_per_run]:
            data = analyze_landing(self.bm, url, f"offer_{oid}_{self.now:%Y%m%d%H%M}")
            self.stats["landing_pages"] += 1
            with session_scope() as s:
                o = s.get(Offer, oid)
                s.add(LandingPage(offer_id=oid, url=url, final_url=data.final_url, status=data.status,
                                  title=data.title, data=data.to_json(), screenshot_path=data.screenshot,
                                  text_excerpt=data.text_excerpt, error=data.error))
                if data.price_brl:
                    o.price_brl, o.price_old_brl = data.price_brl, data.price_old_brl
                    o.price_source = "checkout" if data.checkout_price_brl else "landing"
                o.checkout_platform = data.checkout_platform or o.checkout_platform
                if data.headline and len(data.headline) < 140:
                    o.name = data.headline
                elif data.title:
                    o.name = data.title[:140]
                self.touched_offers.add(oid)
            self.emit("INFO", f"landing {url[:80]}: {data.status}"
                              f"{' preço R$ %.2f' % data.price_brl if data.price_brl else ''}"
                              f"{' — ' + data.error if data.error else ''}", "landing_pages")

    # ------------------------------------------------------------------ E. expansão
    def expand_keywords(self) -> None:
        added = 0
        with session_scope() as s:
            existing = {t.lower() for t in s.scalars(select(Keyword.term))}
            existing_toks = [set(norm_text(t).split()) for t in existing]

            def overlaps(ph: str) -> bool:
                toks = set(ph.split())
                # variante de termo já existente (2+ palavras em comum) não vale nova consulta
                return any(len(toks & e) >= 2 for e in existing_toks)
            for oid in self.touched_offers:
                o = s.get(Offer, oid)
                if not o or o.status == "DISCARDED":
                    continue
                texts = [a.body or "" for a in o.ads if a.is_active][:40] + [a.title or "" for a in o.ads][:20]
                lp = o.landing_pages[-1] if o.landing_pages else None
                if lp and lp.data.get("headline"):
                    texts += [lp.data["headline"]] * 2
                niche, phrases = detect_niche(texts)
                o.niche = niche or o.niche
                for ph in phrases[:3]:
                    if ph.lower() not in existing and len(ph) >= 6 and not overlaps(ph):
                        s.add(Keyword(term=ph, source="expansion", origin_offer_id=o.id,
                                      priority=1.2 + (o.velocity_score or 0) / 100))
                        existing.add(ph.lower())
                        existing_toks.append(set(ph.split()))
                        added += 1
        self.stats["keywords_added"] = added
        self.emit("INFO", f"{added} novas palavras-chave para próximas rodadas", "expansao")

    # ------------------------------------------------------------------ F. demanda
    def validate_demand(self) -> None:
        from radar.research.demand_agent import run_demand
        if not self.search or not self.search.providers:
            self.emit("WARNING", "nenhum provider de busca externa configurado — demanda NOT_VERIFIED",
                      "demanda")
            return
        with session_scope() as s:
            cut = self.now - timedelta(days=7)
            offers = list(s.scalars(
                select(Offer).where(Offer.status.in_(("EMERGING", "WATCHING")))
                .where((Offer.demand_checked_at.is_(None)) | (Offer.demand_checked_at < cut))
                .order_by(Offer.velocity_score.desc().nulls_last())
                .limit(self.s.max_demand_checks_per_run)))
            jobs = [(o.id, ((o.modeling or {}).get("palavras_chave") or [o.niche or o.name])[0]) for o in offers]
        for oid, phrase in jobs:
            if not self.search.usable:
                self.emit("WARNING", "buscas externas bloqueadas — interrompendo validação de demanda",
                          "demanda")
                break
            status, evidence = run_demand(self.search, phrase)
            self.stats["demand_checks"] += 1
            with session_scope() as s:
                o = s.get(Offer, oid)
                o.demand_status, o.demand_checked_at = status, utcnow()
                for e in evidence[:30]:
                    s.add(DemandEvidence(offer_id=oid, **e))
            self.emit("INFO", f"demanda '{phrase}': {status}, {len(evidence)} fontes", "demanda")

    # ------------------------------------------------------------------ G. scoring
    def score_and_alert(self) -> None:
        with session_scope() as s:
            offer_ids = set(self.touched_offers) | set(s.scalars(
                select(Offer.id).where(Offer.status.in_(("EMERGING", "WATCHING", "NEW")))))
        for oid in offer_ids:
            try:
                self._score_offer(oid)
            except Exception as e:  # noqa: BLE001
                self.emit("ERROR", f"scoring da oferta {oid} falhou: {e}", "scoring")
        self._update_advertiser_status()

    def _score_offer(self, oid: int) -> None:
        with session_scope() as s:
            o = s.get(Offer, oid)
            adv = o.advertiser
            active = [a for a in o.ads if a.is_active]
            m = compute_metrics([StoredAd(a) for a in active], self.now)
            snaps = list(s.scalars(select(AdSnapshot).where(AdSnapshot.offer_id == oid)
                                   .order_by(AdSnapshot.taken_at)))
            snaps = [x for x in snaps if x.verification in (VERIFIED, PARTIAL)]
            latest = snaps[-1] if snaps else None
            coverage = latest.coverage if latest else None
            if coverage is not None and coverage >= 0.95:
                series, basis = [(x.taken_at, x.distinct_creatives) for x in snaps], "criativos da oferta"
            else:
                adv_snaps = [x for x in adv.snapshots if x.offer_id is None and x.active_ads_total is not None]
                series = [(x.taken_at, x.active_ads_total) for x in adv_snaps]
                basis = "total de anúncios ativos do anunciante (cobertura parcial)"
            acc = best_acceleration(series, m.retro_curve, self.now)
            texts = [a.body or "" for a in active] + [a.title or "" for a in active]
            lp = o.landing_pages[-1] if o.landing_pages else None
            lpd = (lp.data if lp else {}) or {}

            # triagem no nível da oferta (com preço da landing, se houver)
            price = o.price_brl
            if price is None:
                p, old = guess_offer_price([p for t in texts for p in extract_prices_brl(t)], " ".join(texts))
                if p:
                    o.price_brl, o.price_old_brl, o.price_source = p, old, "ad"
                    price = p
            platform = o.checkout_platform or detect_platform(o.landing_url, *[a.caption for a in active])
            o.checkout_platform = platform
            no_funnel = o.normalized_url == "__sem_link__" or (o.domain or "").endswith(NO_FUNNEL_DOMAINS)
            tr = triage(texts + [lpd.get("headline") or "", lp.text_excerpt[:3000] if lp and lp.text_excerpt else ""],
                        page_categories=adv.page_categories, platform=platform, price=price,
                        cta_types=[a.cta_type for a in active if a.cta_type], has_link=not no_funnel,
                        min_price=self.s.low_ticket_min_brl, max_price=self.s.low_ticket_max_brl)
            o.product_format = tr.product_format or o.product_format
            o.validation = {"checks": tr.checks, "reasons": tr.reasons, "confidence": tr.confidence}
            discarded = not tr.accepted or adv.status == "DISCARDED"
            o.discard_reason = (tr.discard_reason or adv.discard_reason or "anunciante descartado") \
                if discarded else None

            vel = velocity_score(m, acc, coverage=coverage, n_snapshots=len(snaps),
                                 verification=latest.verification if latest else NOT_VERIFIED)
            niche_phrase = next(iter((o.modeling or {}).get("palavras_chave") or []), None)
            kw = s.scalar(select(Keyword).where(Keyword.term == niche_phrase)) if niche_phrase else None
            cluster = s.scalar(select(MarketCluster).where(MarketCluster.name == o.niche)) if o.niche else None
            demand_n = s.scalar(select(func.count(DemandEvidence.id)).where(DemandEvidence.offer_id == oid))
            video_share = (m.formats.get("VIDEO", 0) / m.distinct_creatives) if m.distinct_creatives else 0
            _, phrases = detect_niche(texts)
            blue = blue_ocean_score(
                texts=texts + (lpd.get("bonuses") or []), product_format=o.product_format, price=price,
                platform=platform, has_promise=bool(lpd.get("promise")),
                landing_verified=bool(lp and lp.status == VERIFIED),
                cluster_advertisers=cluster.advertisers_count if cluster else None,
                niche_meta_results=kw.results_last if kw else None, hooks_count=m.hooks_count,
                formats_count=len(m.formats), video_share=video_share, demand_evidence=demand_n or 0,
                specific_niche=bool(phrases))
            stage, why = classify_stage(m, acc, latest.active_ads_total if latest else None)
            status = status_for(stage, acc, vel["score"], discarded=discarded, has_meta_data=bool(snaps))

            from radar.research.modeling import build_modeling
            o.modeling = build_modeling(texts=texts, hooks=m.hooks, niche=o.niche,
                                        product_format=o.product_format, price=price, landing=lpd,
                                        keyphrases=phrases)
            o.metrics = {**m.to_dict(), "active_ads_total_advertiser": adv.active_ads,
                         "coverage": coverage, "series_basis": basis, "stage_reason": why}
            o.acceleration = acc.to_dict()
            o.velocity_score, o.velocity_confidence = vel["score"], vel["confidence"]
            o.blue_ocean_score, o.blue_ocean_confidence = blue["score"], blue["confidence"]
            o.score_breakdown = {"velocity": vel, "blue_ocean": blue}
            o.stage = stage
            o.verification = latest.verification if latest else NOT_VERIFIED
            o.last_analyzed_at = utcnow()
            prev = o.status
            if not o.status_locked and status != prev:
                o.status = status
                o.history = (o.history or []) + [[utcnow().isoformat(), status, why]]
            self.stats["offers_scored"] += 1
            if not discarded:
                self._maybe_alert(s, o, adv, prev, acc, m)

    def _maybe_alert(self, s: Session, o: Offer, adv: Advertiser, prev_status: str, acc, m) -> None:
        alerts = []
        week = self.now.strftime("%G-W%V")
        if o.status == "EMERGING" and (o.velocity_score or 0) >= 55 and prev_status != "EMERGING":
            alerts.append(("EMERGING_SCALE", "high", f"EMERGING:{o.id}:{week}",
                           "🔥 ALERTA DE ESCALA EMERGENTE"))
        if not acc.estimated and acc.rank >= 4:
            alerts.append(("ACCELERATION", "high" if acc.signal == "FORTISSIMA" else "medium",
                           f"ACCEL:{o.id}:{self.now:%Y-%m-%d}", "🚀 ACELERAÇÃO DETECTADA"))
        if not alerts:
            return
        from radar.notifications.base import broadcast
        for typ, sev, key, title in alerts:
            if s.scalar(select(Alert).where(Alert.dedupe_key == key)):
                continue
            text = format_alert(title, o, adv, acc, m)
            alert = Alert(type=typ, severity=sev, offer_id=o.id, advertiser_id=adv.id, title=title,
                          message=text, dedupe_key=key,
                          payload={"velocity": o.velocity_score, "blue_ocean": o.blue_ocean_score,
                                   "signal": acc.signal})
            s.add(alert)
            s.flush()
            channels = broadcast(title, text)
            alert.sent_channels = channels
            alert.sent_at = utcnow() if channels else None
            self.stats["alerts"] += 1
            self.emit("INFO", f"alerta {typ}: {o.name} ({', '.join(channels) or 'sem canal'})", "alertas")

    def _intervention_alert(self, reason: str) -> None:
        from radar.notifications.base import broadcast
        key = f"BLOCK:meta:{self.now:%Y-%m-%d}"
        with session_scope() as s:
            if s.scalar(select(Alert).where(Alert.dedupe_key == key)):
                return
            text = (f"A Meta Ads Library bloqueou a coleta: {reason}.\n"
                    "Rode `python -m radar login` para abrir o navegador persistente e resolver "
                    "manualmente (login/verificação). Candidatos foram salvos e serão "
                    "reanalisados na próxima rodada.")
            a = Alert(type="INTERVENTION_REQUIRED", severity="high", title="⚠️ Intervenção necessária",
                      message=text, dedupe_key=key)
            s.add(a)
            a.sent_channels = broadcast(a.title, text)

    def _update_advertiser_status(self) -> None:
        rank = {"EMERGING": 6, "DECLINING": 5, "WATCHING": 4, "MATURE": 3, "TESTING": 2, "NEW": 1,
                "DISCARDED": 0}
        with session_scope() as s:
            for adv in s.scalars(select(Advertiser).where(Advertiser.status != "DISCARDED")):
                statuses = [o.status for o in adv.offers if o.status != "DISCARDED"]
                if not statuses:
                    if adv.offers and adv.last_checked_at:
                        adv.status, adv.discard_reason = "DISCARDED", "nenhuma oferta passou na triagem"
                    continue
                adv.status = max(statuses, key=lambda x: rank.get(x, 0))
                if adv.last_checked_at:
                    adv.next_check_at = adv.last_checked_at + REVISIT.get(adv.status, timedelta(days=1))
                best = max(adv.offers, key=lambda o: o.velocity_score or 0)
                adv.niche = best.niche

    def update_clusters(self) -> None:
        with session_scope() as s:
            groups: dict[str, list[Offer]] = defaultdict(list)
            for o in s.scalars(select(Offer).where(Offer.status != "DISCARDED", Offer.niche.is_not(None))):
                groups[o.niche].append(o)
            for name, offers in groups.items():
                c = s.scalar(select(MarketCluster).where(MarketCluster.name == name))
                if c is None:
                    c = MarketCluster(name=name)
                    s.add(c)
                    s.flush()
                c.offers_count = len(offers)
                c.advertisers_count = len({o.advertiser_id for o in offers})
                c.emerging_count = sum(1 for o in offers if o.status == "EMERGING")
                vs = [o.velocity_score for o in offers if o.velocity_score is not None]
                c.avg_velocity = round(sum(vs) / len(vs), 1) if vs else None
                kws = []
                for o in offers:
                    kws += (o.modeling or {}).get("palavras_chave", [])[:3]
                c.keywords = list(dict.fromkeys(kws))[:15]
                for o in offers:
                    o.cluster_id = c.id
                    o.advertiser.cluster_id = c.id


# ---------------------------------------------------------------------- helpers
def _offer_name(pa: ParsedAd, key: str) -> str:
    if pa.title and len(pa.title) < 120 and "{{" not in pa.title:
        return pa.title
    if pa.link_description and len(pa.link_description) < 120:
        return pa.link_description
    slug = key.split("/")[-1] if "/" in key else key
    looks_random = bool(re.fullmatch(r"[A-Za-z0-9]{5,12}", slug)) and "-" not in slug and \
        (any(c.isdigit() for c in slug) or slug != slug.lower())
    if (looks_random or not slug) and pa.hook:
        return pa.hook[:120]
    return slug.replace("-", " ").replace("_", " ").strip().title()[:120] or key


def _snapshot(adv_id: int, offer_id: int | None, run_id: int | None, res, m, offer_total: int | None = None,
              taken_at: datetime | None = None) -> AdSnapshot:
    return AdSnapshot(
        advertiser_id=adv_id, offer_id=offer_id, run_id=run_id, taken_at=taken_at or utcnow(),
        active_ads_total=res.total_count if offer_id is None else offer_total,
        observed_ads=m.observed_ads, distinct_creatives=m.distinct_creatives, new_7d=m.new_7d,
        new_14d=m.new_14d, new_30d=m.new_30d, new_40d=m.new_40d, old_active=m.old_active,
        hooks_count=m.hooks_count, formats=m.formats, coverage=res.coverage, verification=res.status)


def format_alert(title: str, o: Offer, adv: Advertiser, acc, m) -> str:
    series = acc.series or []
    counts = " → ".join(str(c) for _, c in series[-3:]) if series else str(m.distinct_creatives)
    span = ""
    if len(series) >= 2:
        d = (datetime.fromisoformat(series[-1][0]) - datetime.fromisoformat(series[-min(3, len(series))][0]))
        span = f" em {max(1, round(d.total_seconds() / 86400))} dias"
    est = " (estimado por datas de início)" if acc.estimated else ""
    price = f"R$ {o.price_brl:.2f}".replace(".", ",") if o.price_brl else "não verificado"
    return (f"{title}\n\nOferta:\n{o.name}\n\nAnunciante:\n{adv.name}\n\n"
            f"Criativos:\n{counts}{span}{est}\n\nNovos anúncios últimos 7 dias:\n{m.new_7d}\n\n"
            f"Criativos antigos ainda ativos:\n{m.old_active}\n\n"
            f"Score de velocidade:\n{o.velocity_score:.0f}/100 (confiança {o.velocity_confidence:.0f})\n\n"
            f"Score Mar Azul:\n{o.blue_ocean_score:.0f}/100 (confiança {o.blue_ocean_confidence:.0f})\n\n"
            f"Preço:\n{price}\n\nMotivo do alerta:\n{acc.explanation or o.metrics.get('stage_reason', '')}"
            f"\n\nLink: {o.landing_url or '-'}")


def run_round(trigger: str = "manual", **kw) -> int | None:
    return Pipeline(trigger, **kw).execute()
