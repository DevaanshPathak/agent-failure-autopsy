"""Runtime settings, read from the environment and the repo-root `.env`."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    # Real environment variables override `.env`. Empty values (`KEY=`) count as unset.
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    tinyfish_api_key: str | None = None
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5-5"
    # Hard cap on total Claude spend (USD), tracked from real token usage across restarts.
    anthropic_budget_usd: float = 4.0
    database_url: str = "sqlite+aiosqlite:///./autopsy.db"
    mode: Literal["live", "replay"] = "live"
    max_attempts: int = 4
    max_credits: int = 40
    proxy_country: str = "US"

    tinyfish_agent_base: str = "https://agent.tinyfish.ai"
    tinyfish_fetch_base: str = "https://api.fetch.tinyfish.ai"
    agent_max_duration_s: int = 150
    agent_min_credits: int = 3
    rules_confidence_threshold: float = 0.8
    fetch_text_max_chars: int = 12000
    replay_speed: float = 1.0
    baseline_default_steps: int = 15
    max_concurrent_live_runs: int = 1
    cors_origins: str = "http://localhost:3000"
    fixtures_dir: Path = REPO_ROOT / "fixtures"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
