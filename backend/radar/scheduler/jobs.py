"""Agendamento: manual | 3x por dia | diário | cron customizado.

Cada disparo roda a rodada em um SUBPROCESSO (`python -m radar run`): um travamento do
navegador não derruba a API, e o RunLock impede rodadas simultâneas.
"""
from __future__ import annotations

import logging
import subprocess
import sys

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from radar.config import BASE_DIR, get_settings
from radar.scheduler.lock import is_running

log = logging.getLogger("radar.scheduler")

PRESETS = {
    "3x": "0 8,14,20 * * *",   # 08h, 14h, 20h (America/Sao_Paulo)
    "daily": "0 9 * * *",
}


def resolve_cron(schedule: str) -> str | None:
    schedule = (schedule or "off").strip()
    if schedule in ("", "off", "manual"):
        return None
    return PRESETS.get(schedule, schedule)


def spawn_run(trigger: str = "scheduled", extra_args: list[str] | None = None) -> bool:
    """Dispara rodada em background. Retorna False se já houver uma em andamento."""
    if is_running():
        log.warning("disparo ignorado: rodada já em execução")
        return False
    cmd = [sys.executable, "-m", "radar", "run", "--trigger", trigger] + (extra_args or [])
    subprocess.Popen(cmd, cwd=str(BASE_DIR), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    return True


def _job():
    spawn_run("scheduled")


def build_scheduler(blocking: bool = False):
    s = get_settings()
    cron = resolve_cron(s.radar_schedule)
    sched = (BlockingScheduler if blocking else BackgroundScheduler)(timezone=s.browser_timezone)
    if cron:
        # max_instances=1 + coalesce: disparos atrasados não se acumulam
        sched.add_job(_job, CronTrigger.from_crontab(cron, timezone=s.browser_timezone), id="radar_round",
                      max_instances=1, coalesce=True, misfire_grace_time=1800, replace_existing=True)
        log.info("agendamento ativo: %s (%s)", s.radar_schedule, cron)
    else:
        log.info("agendamento desligado (RADAR_SCHEDULE=off) — apenas execução manual")
    return sched, cron
