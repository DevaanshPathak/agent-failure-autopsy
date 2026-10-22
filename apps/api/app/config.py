"""Runtime settings, read from the environment and the repo-root `.env`."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_HERE = Path(__file__).resolve()
API_ROOT = _HERE.parents[1]
# In a deploy bundle that holds only apps/api, there is no repo root above it.
REPO_ROOT = _HERE.parents[3] if len(_HERE.parents) > 3 else API_ROOT


def _default_fixtures_dir() -> Path:
    """The repo's fixtures/, or a copy bundled next to the API (the Vercel deploy)."""
    repo = REPO_ROOT / "fixtures"
    return repo if repo.is_dir() else API_ROOT / "fixtures"


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
    anthropic_model: str = "claude-haiku-4-5"
    # Hard cap on total Claude spend (USD), tracked from real token usage across restarts.
    anthropic_budget_usd: float = 4.0
    database_url: str = "sqlite+aiosqlite:///./autopsy.db"
    # Neon (Vercel Marketplace) also sets a direct, non-pgbouncer URL; it is used when present.
    database_url_unpooled: str | None = None
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
    fixtures_dir: Path = Field(default_factory=_default_fixtures_dir)

    # --- Public deployment (docs/deploy.md) ---
    # Serverless hosts stop background work once a response is sent, so a run executes inside
    # the request that streams it (GET /runs/{id}/stream) instead of a background task.
    run_in_stream: bool = False
    # Wall-clock limit per run (seconds), kept under the host's request limit. None = no limit.
    run_deadline_s: float | None = None
    # A queued/running run with no task in this process, older than this, was interrupted.
    stale_run_s: float = 900.0
    # Spend caps shared by every visitor, counted in the database. None = no cap.
    live_credit_cap: int | None = None
    live_runs_per_hour: int | None = None

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
