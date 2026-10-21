"""TinyFish HTTP client and the pure helpers that map its payloads onto our contracts.

Field names follow https://docs.tinyfish.ai (agent-api/reference, fetch-api/reference). We call:
  POST {fetch_base}                        Fetch (page -> markdown), free within a daily allowance
  POST {agent_base}/v1/automation/run-sse  Agent run as an SSE stream (each POST is a billed run)
  GET  {agent_base}/v1/runs/{id}           Run record incl. num_of_steps and steps[]
  POST {agent_base}/v1/runs/{id}/cancel    Idempotent cancel (run-sse runs only)
"""

import asyncio
import copy
import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import httpx

from app.models import AttemptConfig, TraceEvent, TraceKind, TraceSource

USER_AGENT = "agent-failure-autopsy/0.1"
# Fetch: 110 s per-URL backend timeout + 120 s CDN ceiling, so the client waits 150 s.
FETCH_TIMEOUT = httpx.Timeout(150.0, connect=10.0)
# SSE: heartbeats keep the stream alive; a 90 s read gap means the stream is gone.
SSE_TIMEOUT = httpx.Timeout(connect=10.0, read=90.0, write=10.0, pool=10.0)
RUNS_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
CANCEL_TIMEOUT = httpx.Timeout(15.0, connect=10.0)
UI_STRING_LIMIT = 2000


class TinyFishError(Exception):
    """A request TinyFish rejected, or a response we could not use."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int | None = None,
        retry_after: float | None = None,
        request_id: str | None = None,
        raw: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.http_status = http_status
        self.retry_after = retry_after
        self.request_id = request_id
        self.raw = raw

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "http_status": self.http_status,
            "retry_after": self.retry_after,
            "request_id": self.request_id,
        }


def _retry_after(resp: httpx.Response) -> float | None:
    try:
        return float(resp.headers["retry-after"])
    except (KeyError, ValueError):
        return None


def _error_from_response(resp: httpx.Response, content: bytes) -> TinyFishError:
    raw: Any = None
    try:
        raw = json.loads(content)
    except ValueError:
        pass
    err = raw.get("error") if isinstance(raw, dict) else None
    code = err.get("code") if isinstance(err, dict) else None
    message = err.get("message") if isinstance(err, dict) else None
    if not message:
        message = content.decode("utf-8", errors="replace").strip()[:300] or resp.reason_phrase
    request_id = raw.get("request_id") if isinstance(raw, dict) else None
    return TinyFishError(
        (code or f"HTTP_{resp.status_code}").upper(),
        message,
        http_status=resp.status_code,
        retry_after=_retry_after(resp),
        request_id=request_id or resp.headers.get("x-request-id"),
        raw=raw if isinstance(raw, dict) else None,
    )


class TinyFishClient:
    def __init__(
        self,
        api_key: str,
        agent_base: str = "https://agent.tinyfish.ai",
        fetch_base: str = "https://api.fetch.tinyfish.ai",
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.agent_base = agent_base.rstrip("/")
        self.fetch_base = fetch_base.rstrip("/")
        self._http = httpx.AsyncClient(
            headers={"X-API-Key": api_key, "User-Agent": USER_AGENT}, transport=transport
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def fetch(self, url: str) -> dict[str, Any]:
        """Fetch one URL as markdown. Per-URL failures come back in `errors[]` with HTTP 200."""
        body = {"urls": [url], "format": "markdown"}
        for attempt in (1, 2):
            resp = await self._http.post(self.fetch_base, json=body, timeout=FETCH_TIMEOUT)
            if resp.status_code in (429, 503) and attempt == 1:
                await asyncio.sleep(min(_retry_after(resp) or 2.0, 5.0))
                continue
            if resp.is_error:
                raise _error_from_response(resp, resp.content)
            return resp.json()
        raise AssertionError("unreachable")

    async def agent_stream(self, body: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        """Start an agent run and yield each SSE `data:` payload as a dict.

        Never retries: every POST creates a billed run. Non-2xx raises before anything is yielded.
        """
        url = f"{self.agent_base}/v1/automation/run-sse"
        headers = {"Accept": "text/event-stream"}
        async with self._http.stream(
            "POST", url, json=body, headers=headers, timeout=SSE_TIMEOUT
        ) as resp:
            if resp.is_error:
                raise _error_from_response(resp, await resp.aread())
            async for line in resp.aiter_lines():
                if not line or line.startswith(":"):
                    continue
                if not line.startswith("data:"):
                    continue  # `event:` / `id:` / `retry:` lines carry nothing we use
                try:
                    payload = json.loads(line[5:].strip())
                except ValueError:
                    yield {"type": "_UNPARSEABLE", "line": line}
                    continue
                yield (
                    payload if isinstance(payload, dict) else {"type": "_UNPARSEABLE", "line": line}
                )

    async def get_run(self, tf_run_id: str, screenshots: str = "none") -> dict[str, Any]:
        resp = await self._http.get(
            f"{self.agent_base}/v1/runs/{tf_run_id}",
            params={"screenshots": screenshots},
            timeout=RUNS_TIMEOUT,
        )
        if resp.is_error:
            raise _error_from_response(resp, resp.content)
        return resp.json()

    async def cancel(self, tf_run_id: str) -> dict[str, Any]:
        resp = await self._http.post(
            f"{self.agent_base}/v1/runs/{tf_run_id}/cancel", timeout=CANCEL_TIMEOUT
        )
        if resp.is_error:
            raise _error_from_response(resp, resp.content)
        return resp.json()

    async def step_screenshot(self, tf_run_id: str, step_id: str) -> bytes:
        resp = await self._http.get(
            f"{self.agent_base}/v1/runs/{tf_run_id}/steps/{step_id}/screenshot",
            timeout=RUNS_TIMEOUT,
        )
        if resp.is_error:
            raise _error_from_response(resp, resp.content)
        return resp.content


def build_agent_body(cfg: AttemptConfig) -> dict[str, Any]:
    """The exact run-sse body. Never sends beta- or account-gated fields (max_steps, mode,
    capture_config) or `proxy_config.type`, which the run-sse schema doesn't allow."""
    body: dict[str, Any] = {
        "url": cfg.url,
        "goal": cfg.goal,
        "browser_profile": cfg.browser_profile.value,
        "agent_config": {"max_duration_seconds": cfg.max_duration_seconds},
    }
    if cfg.output_schema is not None:
        body["output_schema"] = cfg.output_schema
    if cfg.proxy_enabled:
        body["proxy_config"] = {"enabled": True, "country_code": cfg.proxy_country or "US"}
    return body


# --- Pure mapping helpers ------------------------------------------------------------------------

_SSE_KINDS: dict[str, TraceKind] = {
    "STARTED": TraceKind.started,
    "STREAMING_URL": TraceKind.live_view,
    "PROGRESS": TraceKind.progress,
    "HEARTBEAT": TraceKind.heartbeat,
    "COMPLETE": TraceKind.complete,
    "TF_API_RESULT": TraceKind.tf_api_result,
}


def _sse_label(raw: dict[str, Any], kind: TraceKind) -> str:
    match kind:
        case TraceKind.started:
            return "Agent started"
        case TraceKind.live_view:
            return "Live view ready"
        case TraceKind.progress:
            purpose = raw.get("purpose")
            return (
                purpose.strip() if isinstance(purpose, str) and purpose.strip() else "(no purpose)"
            )
        case TraceKind.heartbeat:
            return "heartbeat"
        case TraceKind.complete:
            return f"Agent finished: {raw.get('status')}"
        case TraceKind.tf_api_result:
            return f"Agent used TinyFish {raw.get('tinyfish_api')}"
    if raw.get("type") == "_UNPARSEABLE":
        return "Unparseable stream line"
    return f"Unknown event {raw.get('type')}"


def map_sse_event(
    raw: dict[str, Any],
    *,
    run_id: str,
    attempt_no: int,
    seq: int,
    step_no: int | None,
    now: datetime,
) -> TraceEvent:
    """Map one run-sse payload onto a TraceEvent, keeping the payload verbatim in `raw`."""
    kind = _SSE_KINDS.get(str(raw.get("type")), TraceKind.unknown)
    tf_run_id = raw.get("run_id")
    tf_timestamp = raw.get("timestamp")
    return TraceEvent(
        run_id=run_id,
        attempt_no=attempt_no,
        seq=seq,
        kind=kind,
        source=TraceSource.tinyfish_sse,
        ts=now,
        tf_timestamp=tf_timestamp if isinstance(tf_timestamp, str) else None,
        tf_run_id=tf_run_id if isinstance(tf_run_id, str) else None,
        step_no=step_no if kind is TraceKind.progress else None,
        label=_sse_label(raw, kind),
        raw=raw,
    )


def normalize_tf_error(obj: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize the error on a COMPLETE event or a run object.

    The docs show `error` both as a string (run-sse OpenAPI, with help_url/help_message beside it)
    and as an object {code, message, category, retry_after, ...}. Codes may be lowercase.
    """
    error = obj.get("error")
    hint = obj.get("profile_hint") if isinstance(obj.get("profile_hint"), dict) else None
    out: dict[str, Any] = {
        "code": None,
        "message": None,
        "category": None,
        "retry_after": None,
        "help_url": obj.get("help_url"),
        "help_message": obj.get("help_message"),
        "profile_hint_reason": None,
    }
    if isinstance(error, str) and error.strip():
        out["message"] = error.strip()
    elif isinstance(error, dict):
        code = error.get("code")
        out["code"] = code.upper() if isinstance(code, str) and code else None
        out["message"] = error.get("message")
        out["category"] = error.get("category")
        out["retry_after"] = error.get("retry_after")
        out["help_url"] = error.get("help_url") or out["help_url"]
        out["help_message"] = error.get("help_message") or out["help_message"]
        if hint is None and isinstance(error.get("profile_hint"), dict):
            hint = error["profile_hint"]
    if hint is not None:
        out["profile_hint_reason"] = hint.get("reason")
    if out["message"] is None and out["code"] is None and out["profile_hint_reason"] is None:
        return None
    return out


def _truncate(value: Any) -> Any:
    if isinstance(value, str) and len(value) > UI_STRING_LIMIT:
        return value[:UI_STRING_LIMIT] + f"…[truncated {len(value) - UI_STRING_LIMIT} chars]"
    if isinstance(value, dict):
        return {k: _truncate(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_truncate(v) for v in value]
    return value


def ui_copy(ev: TraceEvent) -> TraceEvent:
    """Copy for the UI stream: long strings in `raw` (e.g. Fetch page text) are cut to 2,000
    chars. The database keeps the full payload."""
    return ev.model_copy(update={"raw": _truncate(copy.deepcopy(ev.raw))})
