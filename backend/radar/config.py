"""Configuração central do Radar (variáveis de ambiente / .env)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(BASE_DIR / ".env", BASE_DIR.parent / ".env"),
                                      env_prefix="", extra="ignore")

    # --- armazenamento ---
    data_dir: Path = BASE_DIR / "data"
    # SQLite por padrão; para PostgreSQL: postgresql+psycopg://user:pass@host/db
    database_url: str = ""

    # --- navegador ---
    browser_headless: bool = True
    browser_executable_path: str = ""  # vazio = Chromium do Playwright
    browser_ignore_https_errors: bool = False
    browser_locale: str = "pt-BR"
    browser_timezone: str = "America/Sao_Paulo"

    # --- Meta Ads Library ---
    meta_country: str = "BR"
    meta_min_delay_s: float = 8.0          # intervalo mínimo entre navegações na Meta
    meta_cooldown_s: float = 60.0          # espera após limite de taxa (dobra a cada evento)
    meta_max_cooldowns: int = 3            # depois disso a Meta é pausada na rodada
    meta_max_retries: int = 3
    meta_max_pages_per_advertiser: int = 4  # páginas extras (paginação) por anunciante
    meta_max_consecutive_failures: int = 5  # depois disso a Meta é pausada na rodada

    # --- rodada ---
    discovery_min_queries: int = 30
    discovery_max_queries: int = 45
    max_advertisers_per_run: int = 25
    max_landing_pages_per_run: int = 12
    max_demand_checks_per_run: int = 5
    low_ticket_min_brl: float = 10.0
    low_ticket_max_brl: float = 100.0

    # --- busca externa (opcional) ---
    # providers separados por vírgula: brave_api, bing, duckduckgo, google
    search_providers: str = "brave_api,bing,duckduckgo"
    brave_api_key: str = ""

    # --- notificações ---
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # --- agendamento ---
    # off | 3x | daily | expressão cron de 5 campos
    radar_schedule: str = "off"

    # --- API ---
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.data_dir / 'radar.db'}"

    @property
    def browser_profile_dir(self) -> Path:
        return self.data_dir / "browser_profile"

    @property
    def screenshots_dir(self) -> Path:
        return self.data_dir / "screenshots"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.browser_profile_dir, self.screenshots_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s
