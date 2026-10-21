"""Independent verifier: judges every attempt's result itself.

TinyFish documents that `COMPLETED` "means the infrastructure worked, not that your goal
succeeded" (null results, all-empty fields and `{"status": "failure"}` all come back COMPLETED),
so the agent's status is only the first of seven checks.
"""

import json
import re
from collections.abc import Iterator
from typing import Any

from jsonschema import Draft7Validator

from app.models import (
    Attempt,
    BlockSignal,
    BlockSignalKind,
    CheckName,
    CheckResult,
    ExpectedCheck,
    ExpectedCheckType,
    Rung,
    RunRequest,
    SignalWhere,
    TraceEvent,
    TraceKind,
    VerifyResult,
)

# Shared with diagnose/rules.py. All case-insensitive.
RE_CAPTCHA = re.compile(
    r"captcha|recaptcha|hcaptcha|turnstile|i'?m not a robot|verify (that )?you are (a )?human"
    r"|press (and|&) hold|are you a robot|human verification",
    re.I,
)
RE_CAPTCHA_BENIGN = re.compile(r"protected by recaptcha|recaptcha (privacy|terms)", re.I)
RE_LOGIN = re.compile(
    r"sign in to (continue|view)|log ?in to (continue|view)|please (sign|log) ?in|login required"
    r"|you must (be )?(signed|logged) in|enter your password|create an account to (continue|view)",
    re.I,
)
RE_ACCESS_DENIED = re.compile(
    r"access denied|you (have been|are) blocked|request (was )?blocked|unusual traffic"
    r"|checking your browser|just a moment\.\.\.|attention required|pardon our interruption"
    r"|bot detection|security check|forbidden",
    re.I,
)
RE_403 = re.compile(r"\b403\b")
RE_BOT_VENDOR = re.compile(r"cloudflare|datadome|perimeterx|incapsula|imperva|akamai", re.I)
RE_POPUP = re.compile(
    r"cookie|consent|gdpr|banner|pop-?up|modal|overlay|dialog|newsletter|subscribe|accept all"
    r"|interstitial",
    re.I,
)
RE_LOGIN_URL = re.compile(
    r"/(login|log-in|signin|sign-in|sign_in|auth|account/login)(\b|/|\?)", re.I
)

DETAIL_MAX = 200
EVIDENCE_PAD = 60
FETCH_TEXT_SCAN = 5000
FAILURE_STATUSES = {"failure", "failed", "error"}
FAILURE_ONLY_KEYS = {"status", "reason", "error", "message"}

BLOCKING_ANYWHERE = {
    BlockSignalKind.site_blocked_error,
    BlockSignalKind.fetch_bot_blocked,
    BlockSignalKind.fetch_login_required,
    BlockSignalKind.profile_hint_auth_wall,
    BlockSignalKind.profile_hint_bot_challenge,
}
BLOCKING_IN_RESULT = {
    BlockSignalKind.captcha,
    BlockSignalKind.login_form,
    BlockSignalKind.access_denied,
}


# --- Small helpers -------------------------------------------------------------------------------


def cut(text: str, limit: int = DETAIL_MAX) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def get_path(obj: Any, path: str) -> tuple[bool, Any]:
    """Dot path lookup; all-digit segments index lists (`products.0.name`)."""
    cur = obj
    for seg in path.split("."):
        if isinstance(cur, list) and seg.isdigit() and int(seg) < len(cur):
            cur = cur[int(seg)]
        elif isinstance(cur, dict) and seg in cur:
            cur = cur[seg]
        else:
            return False, None
    return True, cur


def is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def all_empty(value: Any) -> bool:
    """True when every leaf of a JSON value is empty (None, "", [] or {})."""
    if isinstance(value, dict):
        return all(all_empty(v) for v in value.values()) if value else True
    if isinstance(value, list):
        return all(all_empty(v) for v in value) if value else True
    return is_empty(value)


def to_json_schema(schema: Any) -> Any:
    """TinyFish output_schema subset -> plain JSON Schema (`nullable` -> type union)."""
    if isinstance(schema, list):
        return [to_json_schema(s) for s in schema]
    if not isinstance(schema, dict):
        return schema
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key in ("nullable", "propertyOrdering"):
            continue
        if key == "properties" and isinstance(value, dict):
            out[key] = {name: to_json_schema(sub) for name, sub in value.items()}
        elif key in ("items", "anyOf"):
            out[key] = to_json_schema(value)
        else:
            out[key] = value
    if schema.get("nullable") is True:
        if isinstance(out.get("type"), str):
            out["type"] = [out["type"], "null"]
        if isinstance(out.get("enum"), list):
            out["enum"] = [*out["enum"], None]
    return out


def _first_seq(trace: list[TraceEvent], *kinds: TraceKind) -> int | None:
    for ev in trace:
        if ev.kind in kinds:
            return ev.seq
    return None


def _evidence(text: str, match: re.Match[str]) -> str:
    start = max(0, match.start() - EVIDENCE_PAD)
    end = min(len(text), match.end() + EVIDENCE_PAD)
    return cut(text[start:end])


# --- Block signals -------------------------------------------------------------------------------


def _signal_sources(
    attempt: Attempt, trace: list[TraceEvent], fetch: dict[str, Any] | None
) -> Iterator[tuple[SignalWhere, str, int | None]]:
    complete_seq = _first_seq(trace, TraceKind.complete)
    if attempt.result is not None:
        yield SignalWhere.result, json.dumps(attempt.result, ensure_ascii=False), complete_seq
    for ev in trace:
        if ev.kind is TraceKind.progress:
            yield SignalWhere.progress, ev.label, ev.seq
    tf_error = attempt.tf_error or {}
    error_text = " ".join(str(tf_error[k]) for k in ("code", "message") if tf_error.get(k))
    if error_text:
        yield SignalWhere.tf_error, error_text, complete_seq
    if fetch:
        results = fetch.get("results") or []
        text = results[0].get("text") if results and isinstance(results[0], dict) else None
        if isinstance(text, str) and text:
            yield (
                SignalWhere.fetch_text,
                text[:FETCH_TEXT_SCAN],
                _first_seq(trace, TraceKind.fetch_result),
            )


def detect_signals(
    attempt: Attempt, trace: list[TraceEvent], fetch: dict[str, Any] | None
) -> list[BlockSignal]:
    """Every block-like signal in the attempt, blocking or not (the diagnoser uses all of them)."""
    signals: list[BlockSignal] = []
    seen: set[tuple[BlockSignalKind, SignalWhere, int | None]] = set()

    def add(kind: BlockSignalKind, where: SignalWhere, evidence: str, seq: int | None) -> None:
        if (kind, where, seq) not in seen:
            seen.add((kind, where, seq))
            signals.append(
                BlockSignal(kind=kind, where=where, evidence=cut(evidence), event_seq=seq)
            )

    for where, text, seq in _signal_sources(attempt, trace, fetch):
        if m := RE_CAPTCHA.search(RE_CAPTCHA_BENIGN.sub(" ", text)):
            add(BlockSignalKind.captcha, where, _evidence(text, m), seq)
        if m := RE_LOGIN.search(text):
            add(BlockSignalKind.login_form, where, _evidence(text, m), seq)
        if m := RE_ACCESS_DENIED.search(text):
            add(BlockSignalKind.access_denied, where, _evidence(text, m), seq)
        if where in (SignalWhere.result, SignalWhere.tf_error) and (m := RE_403.search(text)):
            add(BlockSignalKind.http_403, where, _evidence(text, m), seq)

    complete_seq = _first_seq(trace, TraceKind.complete)
    is_agent = attempt.rung is not Rung.fetch
    if is_agent and attempt.tf_status == "COMPLETED" and attempt.result is None:
        add(
            BlockSignalKind.null_result_completed,
            SignalWhere.result,
            "status=COMPLETED, result=null",
            complete_seq,
        )

    tf_error = attempt.tf_error or {}
    if str(tf_error.get("code") or "").upper() == "SITE_BLOCKED":
        add(
            BlockSignalKind.site_blocked_error,
            SignalWhere.tf_error,
            f"SITE_BLOCKED: {tf_error.get('message') or ''}",
            complete_seq,
        )
    hint = tf_error.get("profile_hint_reason")
    if hint == "auth_wall":
        add(BlockSignalKind.profile_hint_auth_wall, SignalWhere.profile_hint, hint, complete_seq)
    elif hint == "bot_challenge":
        add(
            BlockSignalKind.profile_hint_bot_challenge, SignalWhere.profile_hint, hint, complete_seq
        )

    errors = (fetch or {}).get("errors") or []
    if errors and isinstance(errors[0], dict):
        code, status = errors[0].get("error"), errors[0].get("status")
        seq = _first_seq(trace, TraceKind.fetch_error)
        text = f"{code} {status}" if status else str(code)
        if code == "bot_blocked":
            add(BlockSignalKind.fetch_bot_blocked, SignalWhere.fetch_error, text, seq)
        elif code == "login_required":
            add(BlockSignalKind.fetch_login_required, SignalWhere.fetch_error, text, seq)
        elif code == "target_http_error" and status == 403:
            add(BlockSignalKind.http_403, SignalWhere.fetch_error, text, seq)
    return signals


def is_blocking(signal: BlockSignal) -> bool:
    if signal.kind in BLOCKING_ANYWHERE:
        return True
    return signal.kind in BLOCKING_IN_RESULT and signal.where is SignalWhere.result


# --- Checks --------------------------------------------------------------------------------------


def _check(name: CheckName, passed: bool, detail: str) -> CheckResult:
    return CheckResult(name=name, passed=passed, detail=cut(detail))


def _status_check(attempt: Attempt, fetch: dict[str, Any] | None) -> CheckResult:
    if attempt.rung is Rung.fetch:
        results = (fetch or {}).get("results") or []
        if results:
            return _check(CheckName.tinyfish_status, True, "Fetch returned 1 page")
        errors = (fetch or {}).get("errors") or []
        if errors and isinstance(errors[0], dict):
            status = errors[0].get("status")
            suffix = f" {status}" if status else ""
            return _check(
                CheckName.tinyfish_status, False, f"Fetch error: {errors[0].get('error')}{suffix}"
            )
        code = (attempt.tf_error or {}).get("code") or "no page returned"
        return _check(CheckName.tinyfish_status, False, f"Fetch error: {code}")
    if attempt.tf_status == "COMPLETED":
        return _check(CheckName.tinyfish_status, True, "COMPLETED")
    err = attempt.tf_error or {}
    parts = [attempt.tf_status or "no status", err.get("code"), err.get("message")]
    return _check(CheckName.tinyfish_status, False, " ".join(str(p) for p in parts if p))


def _result_present_check(attempt: Attempt) -> CheckResult:
    result = attempt.result
    if isinstance(result, dict) and result:
        n = len(result)
        return _check(CheckName.result_present, True, f"result has {n} key{'s' if n != 1 else ''}")
    if attempt.rung is Rung.fetch:
        return _check(CheckName.result_present, False, "Extractor found no data in the Fetch text")
    if attempt.tf_status == "COMPLETED" and result is None:
        return _check(
            CheckName.result_present, False, "Agent reported COMPLETED but result is null"
        )
    return _check(CheckName.result_present, False, "result is empty")


def _self_reported_check(result: dict[str, Any]) -> CheckResult:
    status = result.get("status")
    failed = isinstance(status, str) and status.strip().lower() in FAILURE_STATUSES
    failed = failed or not is_empty(result.get("error"))
    keys = set(result)
    failed = failed or (keys <= FAILURE_ONLY_KEYS and bool(keys & {"reason", "error"}))
    if not failed:
        return _check(CheckName.self_reported_failure, True, "no failure reported in the result")
    reason = next(
        (
            result[k]
            for k in ("reason", "error", "message", "status")
            if not is_empty(result.get(k))
        ),
        "failure",
    )
    return _check(CheckName.self_reported_failure, False, f"result reports failure: {reason}")


def _schema_check(result: dict[str, Any], schema: dict[str, Any]) -> CheckResult:
    validator = Draft7Validator(to_json_schema(schema))
    errors = sorted(validator.iter_errors(result), key=lambda e: [str(p) for p in e.absolute_path])
    if not errors:
        return _check(CheckName.output_schema, True, "result matches the output schema")
    shown = "; ".join(
        f"{'/'.join(str(p) for p in e.absolute_path) or '#'}: {e.message}" for e in errors[:3]
    )
    return _check(CheckName.output_schema, False, shown)


def _expected_check(result: dict[str, Any], expected: ExpectedCheck) -> CheckResult:
    haystack = json.dumps(result, ensure_ascii=False)
    name = CheckName.expected
    match expected.type:
        case ExpectedCheckType.contains:
            value = expected.value or ""
            if value.lower() in haystack.lower():
                return _check(name, True, f"found '{value}'")
            return _check(name, False, f"'{value}' not in result")
        case ExpectedCheckType.regex:
            pattern = expected.value or ""
            if re.search(pattern, haystack, re.I):
                return _check(name, True, f"matches /{pattern}/")
            return _check(name, False, f"no match for /{pattern}/")
        case ExpectedCheckType.fields_present:
            fields = expected.fields or []
            missing = [f for f in fields if is_empty(get_path(result, f)[1])]
            if not missing:
                return _check(name, True, f"all {len(fields)} fields present")
            return _check(name, False, f"missing or empty: {', '.join(missing)}")
        case ExpectedCheckType.min_items:
            path, need = expected.path or "", expected.min or 1
            found, value = get_path(result, path)
            if not found or not isinstance(value, list):
                return _check(name, False, f"{path} not found or not a list")
            if len(value) >= need:
                return _check(name, True, f"{path} has {len(value)} items (≥ {need})")
            return _check(name, False, f"{path} has {len(value)} items, need {need}")
    raise AssertionError(f"unhandled expected type {expected.type}")


def verify(
    attempt: Attempt,
    request: RunRequest,
    trace: list[TraceEvent],
    fetch: dict[str, Any] | None,
) -> VerifyResult:
    """Run the checks in spec order. `fetch` is the raw Fetch response for rung-1 attempts."""
    checks = [_status_check(attempt, fetch), _result_present_check(attempt)]
    result = attempt.result
    if checks[-1].passed and isinstance(result, dict):
        checks.append(_self_reported_check(result))
        if attempt.config.output_schema:
            checks.append(_schema_check(result, attempt.config.output_schema))
        if request.expected:
            checks.append(_expected_check(result, request.expected))
        if all_empty(result):
            checks.append(
                _check(CheckName.not_all_null, False, "every field in the result is empty")
            )
        else:
            checks.append(_check(CheckName.not_all_null, True, "result has non-empty values"))

    signals = detect_signals(attempt, trace, fetch)
    blocking = [s for s in signals if is_blocking(s)]
    if blocking:
        first = blocking[0]
        checks.append(
            _check(
                CheckName.no_block_page,
                False,
                f"{first.kind.value} in {first.where.value}: '{first.evidence}'",
            )
        )
    else:
        checks.append(_check(CheckName.no_block_page, True, "no blocking page detected"))

    passed = all(c.passed for c in checks)
    if passed:
        expected = next((c for c in checks if c.name is CheckName.expected), None)
        summary = "Verified: " + (expected.detail if expected else "result passed all checks")
    else:
        summary = "Rejected: " + next(c.detail for c in checks if not c.passed)
    return VerifyResult(
        attempt_no=attempt.attempt_no,
        passed=passed,
        checks=checks,
        block_signals=signals,
        summary=cut(summary),
    )
