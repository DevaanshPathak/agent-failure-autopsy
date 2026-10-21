"""Developer endpoints that need no API keys and no database."""

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from sse_starlette import EventSourceResponse, ServerSentEvent

from app.config import get_settings

router = APIRouter(prefix="/dev", tags=["dev"])

SAMPLE_FILE = "sample-run.jsonl"


def read_jsonl_lines(path: Path) -> list[str]:
    """Non-empty lines of a JSONL file. `splitlines` copes with CRLF checkouts on Windows."""
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@router.get("/sample-stream")
async def sample_stream(delay_ms: int = Query(400, ge=0, le=5000)) -> EventSourceResponse:
    path = get_settings().fixtures_dir / SAMPLE_FILE
    if not path.is_file():
        raise HTTPException(status_code=500, detail=f"fixtures/{SAMPLE_FILE} not found")
    lines = read_jsonl_lines(path)

    async def events() -> AsyncIterator[ServerSentEvent]:
        for i, line in enumerate(lines):
            if i and delay_ms:
                await asyncio.sleep(delay_ms / 1000)
            yield ServerSentEvent(data=line, id=str(json.loads(line)["seq"]))

    return EventSourceResponse(events(), ping=15, sep="\n")
