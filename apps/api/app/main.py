"""FastAPI app: run it as a single uvicorn worker (runs and the event bus live in memory)."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__, db
from app.config import Settings, get_settings
from app.events import RunEventBus
from app.ladder.controller import LadderController
from app.models import Health, RunMode
from app.routes import dev, runs
from app.services import Services
from app.tinyfish.client import TinyFishClient

_UNSET: Any = object()


def build_services(settings: Settings, *, tinyfish: Any = _UNSET, claude: Any = _UNSET) -> Services:
    """Clients are built only when their API key exists. Tests inject fakes."""
    if tinyfish is _UNSET:
        tinyfish = (
            TinyFishClient(
                settings.tinyfish_api_key,
                settings.tinyfish_agent_base,
                settings.tinyfish_fetch_base,
            )
            if settings.tinyfish_api_key
            else None
        )
    if claude is _UNSET:
        claude = None  # Phase 3 builds the Claude client here.
    bus = RunEventBus()
    return Services(
        settings=settings,
        tinyfish=tinyfish,
        claude=claude,
        bus=bus,
        controller=LadderController(settings, tinyfish, claude, bus),
        live_semaphore=asyncio.Semaphore(settings.max_concurrent_live_runs),
    )


def create_app(
    settings: Settings | None = None, *, tinyfish: Any = _UNSET, claude: Any = _UNSET
) -> FastAPI:
    settings = settings or get_settings()
    services = build_services(settings, tinyfish=tinyfish, claude=claude)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await db.init_db()
        yield
        for task in list(services.tasks):
            task.cancel()
        if services.tinyfish is not None and hasattr(services.tinyfish, "aclose"):
            await services.tinyfish.aclose()
        await db.dispose()

    app = FastAPI(title="Agent Failure Autopsy", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.services = services
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(dev.router)
    app.include_router(runs.router)

    @app.get("/health", response_model=Health, tags=["meta"])
    async def health() -> Health:
        return Health(
            status="ok",
            mode=RunMode(settings.mode),
            tinyfish_key=bool(settings.tinyfish_api_key),
            anthropic_key=bool(settings.anthropic_api_key),
            db="ok" if await db.ping() else "error",
            version=__version__,
        )

    return app


app = create_app()
