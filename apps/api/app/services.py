"""Long-lived objects shared by the routes (one process, ADR-012)."""

import asyncio
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request

from app.config import Settings
from app.events import RunEventBus
from app.ladder.controller import LadderController
from app.tinyfish.client import TinyFishClient


@dataclass
class Services:
    settings: Settings
    tinyfish: TinyFishClient | None
    claude: Any
    bus: RunEventBus
    controller: LadderController
    live_semaphore: asyncio.Semaphore
    tasks: set[asyncio.Task[None]] = field(default_factory=set)
    run_tasks: dict[str, asyncio.Task[None]] = field(default_factory=dict)

    def track(self, run_id: str, task: asyncio.Task[None]) -> None:
        self.tasks.add(task)
        self.run_tasks[run_id] = task

        def _done(t: asyncio.Task[None]) -> None:
            self.tasks.discard(t)
            if self.run_tasks.get(run_id) is t:
                del self.run_tasks[run_id]

        task.add_done_callback(_done)


def get_services(request: Request) -> Services:
    return request.app.state.services
