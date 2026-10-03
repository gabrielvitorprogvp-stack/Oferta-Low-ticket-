"""Garante uma única rodada por vez (lock de arquivo do SO + verificação no banco).

O lock de arquivo (fcntl) é liberado automaticamente pelo SO se o processo morrer,
então não existe lock "preso". Rodadas marcadas como running sem heartbeat recente são
fechadas como 'failed' (processo morreu).
"""
from __future__ import annotations

import fcntl
import os
from radar.config import get_settings
from radar.database.models import ResearchRun, utcnow
from radar.database.session import session_scope


class RunLock:
    def __init__(self):
        self.path = get_settings().data_dir / "run.lock"
        self.fd = None

    def acquire(self) -> bool:
        self.fd = os.open(self.path, os.O_CREAT | os.O_RDWR)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(self.fd)
            self.fd = None
            return False
        os.ftruncate(self.fd, 0)
        os.write(self.fd, str(os.getpid()).encode())
        return True

    def release(self) -> None:
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()


def is_running() -> bool:
    lock = RunLock()
    if lock.acquire():
        lock.release()
        return False
    return True


def close_stale_runs() -> int:
    """Chamado com o lock adquirido: qualquer 'running' no banco é órfão."""
    n = 0
    with session_scope() as s:
        for r in s.query(ResearchRun).filter(ResearchRun.status == "running"):
            r.status = "failed"
            r.error = (r.error or "") + " | processo interrompido (rodada órfã fechada)"
            r.finished_at = utcnow()
            n += 1
    return n
