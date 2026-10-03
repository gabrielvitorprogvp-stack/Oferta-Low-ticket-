import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "")
    from radar import config
    from radar.database import session
    config.get_settings.cache_clear()
    session.reset_engine()
    session.init_db()
    yield tmp_path
    session.reset_engine()
    config.get_settings.cache_clear()
