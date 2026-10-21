"""FastAPI app: run it as a single uvicorn worker (runs and the event bus live in memory)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__, db
from app.config import Settings, get_settings
from app.models import Health, RunMode
from app.routes import dev


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await db.init_db()
        yield
        await db.dispose()

    app = FastAPI(title="Agent Failure Autopsy", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(dev.router)

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
