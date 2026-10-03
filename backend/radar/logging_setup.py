from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from radar.config import get_settings


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if getattr(root, "_radar_configured", False):
        return
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root.setLevel(level)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    fh = RotatingFileHandler(get_settings().logs_dir / "radar.log", maxBytes=5_000_000, backupCount=5,
                             encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(sh)
    root.addHandler(fh)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    root._radar_configured = True  # type: ignore[attr-defined]
