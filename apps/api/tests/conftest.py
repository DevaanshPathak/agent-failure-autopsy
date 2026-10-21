"""Shared pytest fixtures."""

from pathlib import Path

import pytest

from app import db
from app.config import REPO_ROOT
from app.routes.dev import read_jsonl_lines

SAMPLE_RUN = REPO_ROOT / "fixtures" / "sample-run.jsonl"


@pytest.fixture
def sample_lines() -> list[str]:
    return read_jsonl_lines(SAMPLE_RUN)


@pytest.fixture
async def temp_db(tmp_path: Path):
    db.configure(f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}")
    await db.init_db()
    yield
    await db.dispose()
