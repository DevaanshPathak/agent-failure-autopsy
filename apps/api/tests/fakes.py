"""Scripted stand-ins for the TinyFish and Claude clients (tests never touch the network)."""

from collections.abc import AsyncIterator
from typing import Any


class FakeTinyFish:
    """Each call pops the next scripted response; an Exception in a script is raised."""

    def __init__(
        self,
        *,
        fetch: list[Any] | None = None,
        streams: list[Any] | None = None,
        runs: dict[str, Any] | None = None,
        polls: dict[str, list[dict[str, Any]]] | None = None,
    ) -> None:
        self.fetch_script = list(fetch or [])
        self.stream_script = list(streams or [])
        self.runs = runs or {}
        self.polls = polls or {}
        self.bodies: list[dict[str, Any]] = []
        self.fetched: list[str] = []
        self.cancelled: list[str] = []

    async def fetch(self, url: str) -> dict[str, Any]:
        self.fetched.append(url)
        item = self.fetch_script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def agent_stream(self, body: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        self.bodies.append(body)
        script = self.stream_script.pop(0)
        if isinstance(script, Exception):
            raise script
        for event in script:
            if isinstance(event, Exception):
                raise event
            yield event

    async def get_run(self, tf_run_id: str, screenshots: str = "none") -> dict[str, Any]:
        if self.polls.get(tf_run_id):
            return self.polls[tf_run_id].pop(0)
        return self.runs.get(tf_run_id, {"run_id": tf_run_id, "status": "COMPLETED"})

    async def cancel(self, tf_run_id: str) -> dict[str, Any]:
        self.cancelled.append(tf_run_id)
        return {"run_id": tf_run_id, "status": "CANCELLED"}

    async def step_screenshot(self, tf_run_id: str, step_id: str) -> bytes:
        return b"\xff\xd8fake-jpeg"

    async def aclose(self) -> None:
        return None


def sse_run(
    tf_run_id: str,
    purposes: list[str],
    *,
    status: str = "COMPLETED",
    result: dict[str, Any] | None = None,
    extra_complete: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """A TinyFish-shaped run-sse event list: STARTED, STREAMING_URL, PROGRESS..., COMPLETE."""
    events: list[dict[str, Any]] = [
        {"type": "STARTED", "run_id": tf_run_id, "timestamp": "2026-11-01T11:00:00Z"},
        {
            "type": "STREAMING_URL",
            "run_id": tf_run_id,
            "streaming_url": f"https://{tf_run_id}.invalid/stream/0",
            "timestamp": "2026-11-01T11:00:01Z",
        },
        {"type": "HEARTBEAT", "timestamp": "2026-11-01T11:00:02Z"},
    ]
    for i, purpose in enumerate(purposes, start=1):
        events.append(
            {
                "type": "PROGRESS",
                "run_id": tf_run_id,
                "purpose": purpose,
                "timestamp": f"2026-11-01T11:00:{10 + i:02d}Z",
            }
        )
    events.append(
        {
            "type": "COMPLETE",
            "run_id": tf_run_id,
            "status": status,
            "result": result,
            "timestamp": "2026-11-01T11:00:59Z",
            **(extra_complete or {}),
        }
    )
    return events


def run_record(tf_run_id: str, steps: int, *, proxy: bool = False) -> dict[str, Any]:
    return {
        "run_id": tf_run_id,
        "status": "COMPLETED",
        "num_of_steps": steps,
        "browser_config": {"proxy_enabled": proxy, "proxy_country_code": "US" if proxy else None},
        "steps": [
            {
                "id": f"{tf_run_id}-s{i}",
                "timestamp": f"2026-11-01T11:00:{10 + i:02d}Z",
                "action": f"step {i}",
            }
            for i in range(1, steps + 1)
        ],
    }
