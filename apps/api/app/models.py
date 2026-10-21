"""API contracts: the single source of truth.

JSON Schema (shared/schemas/contracts.schema.json) and the web app's TypeScript types
(apps/web/lib/types.ts) are generated from this module by `make types`.
"""

import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    StringConstraints,
    TypeAdapter,
    field_validator,
    model_validator,
)

from app.patch.planner import tinyfish_schema_errors


class _Model(BaseModel):
    # Defaulted fields are always present in responses, so the exported (serialization) schema
    # marks them required; the generated TypeScript then has no needless optionals.
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)


# --- Enums -------------------------------------------------------------------------------------


class FailureClass(StrEnum):
    needs_interaction = "needs_interaction"
    popup_overlay = "popup_overlay"
    bot_block = "bot_block"
    misread_page = "misread_page"
    auth_wall = "auth_wall"
    captcha = "captcha"


class Rung(StrEnum):
    fetch = "fetch"
    agent = "agent"
    agent_stealth = "agent_stealth"


class ExpectedCheckType(StrEnum):
    contains = "contains"
    regex = "regex"
    fields_present = "fields_present"
    min_items = "min_items"


class TraceKind(StrEnum):
    started = "started"
    live_view = "live_view"
    progress = "progress"
    heartbeat = "heartbeat"
    complete = "complete"
    tf_api_result = "tf_api_result"
    fetch_result = "fetch_result"
    fetch_error = "fetch_error"
    extraction = "extraction"
    run_snapshot = "run_snapshot"
    stream_error = "stream_error"
    system = "system"
    unknown = "unknown"


class TraceSource(StrEnum):
    tinyfish_sse = "tinyfish_sse"
    tinyfish_fetch = "tinyfish_fetch"
    tinyfish_runs = "tinyfish_runs"
    claude_extract = "claude_extract"
    system = "system"


class CheckName(StrEnum):
    tinyfish_status = "tinyfish_status"
    result_present = "result_present"
    self_reported_failure = "self_reported_failure"
    output_schema = "output_schema"
    expected = "expected"
    not_all_null = "not_all_null"
    no_block_page = "no_block_page"


class BlockSignalKind(StrEnum):
    access_denied = "access_denied"
    http_403 = "http_403"
    login_form = "login_form"
    captcha = "captcha"
    null_result_completed = "null_result_completed"
    site_blocked_error = "site_blocked_error"
    profile_hint_auth_wall = "profile_hint_auth_wall"
    profile_hint_bot_challenge = "profile_hint_bot_challenge"
    fetch_bot_blocked = "fetch_bot_blocked"
    fetch_login_required = "fetch_login_required"


class SignalWhere(StrEnum):
    result = "result"
    progress = "progress"
    tf_error = "tf_error"
    fetch_error = "fetch_error"
    fetch_text = "fetch_text"
    profile_hint = "profile_hint"


class EvidenceSource(StrEnum):
    trace = "trace"
    result = "result"
    fetch_text = "fetch_text"
    verifier = "verifier"
    tinyfish_error = "tinyfish_error"


class DiagnosisSource(StrEnum):
    rules = "rules"
    llm = "llm"
    rules_fallback = "rules_fallback"


class AttemptOutcome(StrEnum):
    verified = "verified"
    rejected = "rejected"
    cancelled_budget = "cancelled_budget"
    error = "error"


class RunStatus(StrEnum):
    queued = "queued"
    running = "running"
    verified = "verified"
    unrecoverable = "unrecoverable"
    budget_exhausted = "budget_exhausted"
    error = "error"
    cancelled = "cancelled"


class RunMode(StrEnum):
    live = "live"
    replay = "replay"


class BrowserProfile(StrEnum):
    lite = "lite"
    stealth = "stealth"


RUNG_ORDER: list[Rung] = [Rung.fetch, Rung.agent, Rung.agent_stealth]
RECOVERABLE: frozenset[FailureClass] = frozenset(
    {
        FailureClass.needs_interaction,
        FailureClass.popup_overlay,
        FailureClass.bot_block,
        FailureClass.misread_page,
    }
)
RUNG_LABEL: dict[Rung, str] = {
    Rung.fetch: "Rung 1 · Fetch",
    Rung.agent: "Rung 2 · Agent",
    Rung.agent_stealth: "Rung 3 · Agent + stealth + proxy",
}
VERDICT_STATUSES: frozenset[RunStatus] = frozenset(
    {
        RunStatus.verified,
        RunStatus.unrecoverable,
        RunStatus.budget_exhausted,
        RunStatus.error,
        RunStatus.cancelled,
    }
)


# --- Requests and attempt config ---------------------------------------------------------------


class ExpectedCheck(_Model):
    """The user's independent check on the result."""

    type: ExpectedCheckType
    value: str | None = None
    fields: list[str] | None = None
    path: str | None = None
    min: int | None = None

    @model_validator(mode="after")
    def _check_shape(self) -> "ExpectedCheck":
        if self.type in (ExpectedCheckType.contains, ExpectedCheckType.regex):
            if not self.value:
                raise ValueError(f"expected.value is required for type '{self.type}'")
            if self.type is ExpectedCheckType.regex:
                try:
                    re.compile(self.value)
                except re.error as e:
                    raise ValueError(f"expected.value is not a valid regex: {e}") from e
        elif self.type is ExpectedCheckType.fields_present:
            if not self.fields or not all(f.strip() for f in self.fields):
                raise ValueError("expected.fields must list at least one non-empty path")
        elif self.type is ExpectedCheckType.min_items:
            if not self.path:
                raise ValueError("expected.path is required for type 'min_items'")
            if self.min is None or self.min < 1:
                raise ValueError("expected.min must be an integer >= 1 for type 'min_items'")
        return self


Goal = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class RunRequest(_Model):
    """Body of POST /runs."""

    url: str
    goal: Goal
    expected: ExpectedCheck | None = None
    output_schema: dict[str, Any] | None = None
    site_id: str | None = None
    mode: RunMode | None = None
    start_rung: Rung = Rung.fetch
    max_attempts: int | None = Field(default=None, ge=1, le=8)
    max_credits: int | None = Field(default=None, ge=0, le=500)

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        return v

    @field_validator("output_schema")
    @classmethod
    def _check_output_schema(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is not None:
            errors = tinyfish_schema_errors(v)
            if errors:
                raise ValueError("output_schema: " + "; ".join(errors))
        return v


class AttemptConfig(_Model):
    """Exactly what one attempt runs with."""

    attempt_no: int
    rung: Rung
    url: str
    goal: str
    output_schema: dict[str, Any] | None = None
    browser_profile: BrowserProfile = BrowserProfile.lite
    proxy_enabled: bool = False
    proxy_country: str | None = None
    max_duration_seconds: int
    from_fetch_cache: bool = False
    patches_applied: list[str] = Field(default_factory=list)
    credit_limit: int


# --- Trace, verification, diagnosis --------------------------------------------------------------


class TraceEvent(_Model):
    run_id: str
    attempt_no: int
    seq: int
    kind: TraceKind
    source: TraceSource
    ts: datetime
    tf_timestamp: str | None = None
    tf_run_id: str | None = None
    step_no: int | None = None
    label: str
    raw: dict[str, Any]


class CheckResult(_Model):
    name: CheckName
    passed: bool
    detail: str


class BlockSignal(_Model):
    kind: BlockSignalKind
    where: SignalWhere
    evidence: str
    event_seq: int | None = None


class VerifyResult(_Model):
    attempt_no: int
    passed: bool
    checks: list[CheckResult]
    block_signals: list[BlockSignal]
    summary: str


class Evidence(_Model):
    source: EvidenceSource
    quote: str
    event_seq: int | None = None


class Patch(_Model):
    next_rung: Rung | None = None
    skip_rungs: list[Rung] = Field(default_factory=list)
    goal_prefix: str | None = None
    goal_suffix: str | None = None
    output_schema: dict[str, Any] | None = None
    browser_profile: BrowserProfile | None = None
    proxy_enabled: bool | None = None
    reextract_from_fetch: bool = False
    stop: bool = False
    stop_reason: str | None = None
    summary: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _stop_needs_reason(self) -> "Patch":
        if self.stop and not self.stop_reason:
            raise ValueError("patch.stop_reason is required when patch.stop is true")
        return self


class Diagnosis(_Model):
    attempt_no: int
    failure_class: FailureClass
    recoverable: bool
    confidence: float = Field(ge=0, le=1)
    failing_step_seq: int | None = None
    failing_step_label: str | None = None
    evidence: list[Evidence] = Field(min_length=1, max_length=5)
    explanation: str
    patch: Patch
    source: DiagnosisSource


# --- Attempts and runs ---------------------------------------------------------------------------


class Attempt(_Model):
    attempt_no: int
    rung: Rung
    config: AttemptConfig
    started_at: datetime
    finished_at: datetime | None = None
    tf_run_id: str | None = None
    streaming_url: str | None = None
    tf_status: str | None = None
    tf_error: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    progress_count: int = 0
    num_of_steps: int | None = None
    credits_estimated: int = 0
    verify: VerifyResult | None = None
    diagnosis: Diagnosis | None = None
    outcome: AttemptOutcome | None = None


class Run(_Model):
    id: str
    created_at: datetime
    finished_at: datetime | None = None
    mode: RunMode
    request: RunRequest
    status: RunStatus
    attempts: list[Attempt] = Field(default_factory=list)
    credits_used: int = 0
    max_attempts: int
    max_credits: int
    final_result: dict[str, Any] | None = None
    verdict_reason: str | None = None
    baseline_credits_estimate: int | None = None


# --- UI events (streamed to the web app) ---------------------------------------------------------


class _UiBase(_Model):
    # `type` is declared first so it serializes first; each variant narrows it to a literal.
    type: str
    seq: int
    run_id: str
    ts: datetime


class AttemptStartedEvent(_UiBase):
    type: Literal["attempt_started"] = "attempt_started"
    attempt_no: int
    rung: Rung
    config: AttemptConfig


class TraceUiEvent(_UiBase):
    type: Literal["trace_event"] = "trace_event"
    attempt_no: int
    event: TraceEvent


class LiveViewEvent(_UiBase):
    type: Literal["live_view"] = "live_view"
    attempt_no: int
    streaming_url: str


class VerifyEvent(_UiBase):
    type: Literal["verify"] = "verify"
    attempt_no: int
    result: VerifyResult


class DiagnosisEvent(_UiBase):
    type: Literal["diagnosis"] = "diagnosis"
    attempt_no: int
    diagnosis: Diagnosis


class RungChangeEvent(_UiBase):
    type: Literal["rung_change"] = "rung_change"
    from_rung: Rung | None = None
    to_rung: Rung
    skipped: list[Rung] = Field(default_factory=list)
    reason: str


class BudgetEvent(_UiBase):
    type: Literal["budget"] = "budget"
    attempts_used: int
    max_attempts: int
    credits_used: int
    max_credits: int


class VerdictEvent(_UiBase):
    type: Literal["verdict"] = "verdict"
    status: RunStatus
    reason: str
    final_result: dict[str, Any] | None = None
    attempts_used: int
    credits_used: int
    baseline_credits_estimate: int | None = None

    @field_validator("status")
    @classmethod
    def _final_status(cls, v: RunStatus) -> RunStatus:
        if v not in VERDICT_STATUSES:
            raise ValueError(f"verdict status must be final, got '{v}'")
        return v


UiEventUnion = Annotated[
    AttemptStartedEvent
    | TraceUiEvent
    | LiveViewEvent
    | VerifyEvent
    | DiagnosisEvent
    | RungChangeEvent
    | BudgetEvent
    | VerdictEvent,
    Field(discriminator="type"),
]
UiEventAdapter: TypeAdapter[UiEventUnion] = TypeAdapter(UiEventUnion)


class UiEvent(RootModel[UiEventUnion]):
    """Exists only so the schema export names the TypeScript union `UiEvent`."""


# --- Claude structured-output models (kept flat on purpose) --------------------------------------


class FetchExtraction(_Model):
    found: bool
    result_json: str
    missing: list[str]
    interaction_hint: str


class LlmDiagnosis(_Model):
    failure_class: FailureClass
    confidence: float
    failing_step_seq: int | None
    evidence_quotes: list[str]
    explanation: str
    suggested_goal_prefix: str
    suggested_goal_suffix: str


# --- Sites, stats, misc responses ----------------------------------------------------------------


class SiteInfo(_Model):
    id: str
    url: str
    goal: str
    expected: ExpectedCheck | None = None
    expected_class: FailureClass | None = None
    notes: str | None = None
    output_schema: dict[str, Any] | None = None
    baseline_steps: int | None = None
    start_rung: Rung | None = None
    has_trace: bool = False


class RunCreated(_Model):
    run_id: str
    mode: RunMode
    stream_url: str


class Health(_Model):
    status: Literal["ok"] = "ok"
    mode: RunMode
    tinyfish_key: bool
    anthropic_key: bool
    db: Literal["ok", "error"]
    version: str


class StatsRow(_Model):
    run_id: str
    created_at: datetime
    site_id: str | None = None
    url: str
    mode: RunMode
    status: RunStatus
    attempts: int
    credits_used: int
    baseline_credits_estimate: int | None = None
    classes: list[FailureClass]


class Stats(_Model):
    include_replay: bool
    runs_total: int
    runs_finished: int
    diagnosed: int
    fixed: int
    verified_first_try: int
    unrecoverable: int
    budget_exhausted: int
    errors: int
    credits_used_total: int
    baseline_credits_total: int
    credits_saved: int
    by_class: dict[FailureClass, int]
    rows: list[StatsRow]
