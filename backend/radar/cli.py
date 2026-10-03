"""CLI: python -m radar <comando>

  init                 cria o banco e as palavras-semente
  run [opções]         executa uma rodada agora (manual)
  login                abre navegador visível com o perfil persistente (login/verificação manual)
  serve                API + dashboard (+ scheduler, se RADAR_SCHEDULE != off)
  scheduler            só o scheduler (processo bloqueante)
  rescore              recalcula scores/status das ofertas (sem navegar)
  export-artifact      exporta os dados para o app (artifact) no claude.ai
  test-telegram        envia mensagem de teste
"""
from __future__ import annotations

import argparse
import sys

from radar.logging_setup import setup_logging


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="radar", description="Radar Low Ticket — Escala Emergente")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    r = sub.add_parser("run")
    r.add_argument("--trigger", default="manual")
    r.add_argument("--max-queries", type=int)
    r.add_argument("--max-advertisers", type=int)
    r.add_argument("--skip-external", action="store_true", help="não usa Google/Bing/DDG/Brave")
    r.add_argument("--skip-landing", action="store_true")
    r.add_argument("--term", action="append", help="consulta específica (repetível)")
    lg = sub.add_parser("login")
    lg.add_argument("--url", default="https://www.facebook.com/ads/library/")
    sub.add_parser("serve")
    sub.add_parser("scheduler")
    sub.add_parser("test-telegram")
    sub.add_parser("rescore", help="recalcula scores/status de todas as ofertas sem navegar")
    ex = sub.add_parser("export-artifact", help="exporta ofertas/resumo em JSON para o app (artifact)")
    ex.add_argument("--out", default=None)
    a = p.parse_args(argv)
    setup_logging()

    if a.cmd == "init":
        from radar.database.session import init_db
        from radar.pipeline import Pipeline
        init_db()
        Pipeline()._seed_keywords()
        print("banco inicializado")
    elif a.cmd == "run":
        from radar.pipeline import run_round
        rid = run_round(a.trigger, max_queries=a.max_queries, max_advertisers=a.max_advertisers,
                        skip_external=a.skip_external, skip_landing=a.skip_landing, terms=a.term)
        if rid is None:
            print("já existe uma rodada em execução")
            return 2
        print(f"rodada #{rid} concluída")
    elif a.cmd == "login":
        from radar.crawler.browser import interactive_login
        interactive_login(a.url)
    elif a.cmd == "serve":
        import uvicorn
        from radar.config import get_settings
        s = get_settings()
        uvicorn.run("radar.api.app:app", host=s.api_host, port=s.api_port)
    elif a.cmd == "scheduler":
        from radar.database.session import init_db
        from radar.scheduler.jobs import build_scheduler
        init_db()
        sched, cron = build_scheduler(blocking=True)
        if not cron:
            print("RADAR_SCHEDULE=off — nada para agendar")
            return 1
        sched.start()
    elif a.cmd == "rescore":
        from sqlalchemy import select
        from radar.database.models import Offer
        from radar.database.session import init_db, session_scope
        from radar.pipeline import Pipeline
        init_db()
        pl = Pipeline("rescore")
        with session_scope() as s:
            pl.touched_offers = set(s.scalars(select(Offer.id)))
        # reaplica a extração de preço (regras atuais) ao texto já salvo das landing pages
        from radar.database.models import LandingPage
        from radar.research.text_utils import extract_prices_brl, guess_offer_price
        with session_scope() as s:
            for o in s.scalars(select(Offer).where(Offer.price_source == "landing")):
                lp = s.scalar(select(LandingPage).where(LandingPage.offer_id == o.id)
                              .order_by(LandingPage.fetched_at.desc()).limit(1))
                if lp and lp.text_excerpt:
                    o.price_brl, o.price_old_brl = guess_offer_price(extract_prices_brl(lp.text_excerpt),
                                                                     lp.text_excerpt)
        pl.expand_keywords()
        pl.score_and_alert()
        pl.update_clusters()
        pl.score_and_alert()  # 2ª passada usa os clusters atualizados
        print(f"{len(pl.touched_offers)} ofertas recalculadas")
    elif a.cmd == "export-artifact":
        from radar.export import export_artifact
        out = export_artifact(a.out)
        print(f"exportado em {out}")
    elif a.cmd == "test-telegram":
        from radar.notifications.telegram import TelegramNotifier
        t = TelegramNotifier()
        if not t.enabled:
            print("defina TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID")
            return 1
        print("enviado" if t.send("Radar Low Ticket", "✅ Teste de notificação do Radar") else "falhou")
    return 0


if __name__ == "__main__":
    sys.exit(main())
