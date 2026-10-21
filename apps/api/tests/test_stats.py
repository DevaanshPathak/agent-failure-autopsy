from datetime import UTC, datetime, timedelta

from app.models import (
    Attempt,
    AttemptConfig,
    Diagnosis,
    Evidence,
    EvidenceSource,
    FailureClass,
    Patch,
    Run,
    Rung,
    RunMode,
    RunRequest,
    RunStatus,
)
from app.stats import compute_stats

T0 = datetime(2026, 11, 1, 11, 0, tzinfo=UTC)
REQ = RunRequest(url="https://x.example", goal="g", site_id="s1")


def _attempt(n: int, cls: FailureClass | None) -> Attempt:
    cfg = AttemptConfig(
        attempt_no=n, rung=Rung.agent, url=REQ.url, goal="g", max_duration_seconds=1, credit_limit=1
    )
    diagnosis = None
    if cls is not None:
        diagnosis = Diagnosis(
            attempt_no=n,
            failure_class=cls,
            recoverable=True,
            confidence=0.9,
            evidence=[Evidence(source=EvidenceSource.verifier, quote="x")],
            explanation="x",
            patch=Patch(),
            source="rules",
        )
    return Attempt(attempt_no=n, rung=Rung.agent, config=cfg, started_at=T0, diagnosis=diagnosis)


def _run(
    i: int, status: RunStatus, classes: list, credits: int, baseline: int | None, mode=RunMode.live
) -> Run:
    return Run(
        id=f"r{i}",
        created_at=T0 + timedelta(minutes=i),
        mode=mode,
        request=REQ,
        status=status,
        attempts=[_attempt(n + 1, c) for n, c in enumerate(classes)],
        credits_used=credits,
        max_attempts=4,
        max_credits=40,
        baseline_credits_estimate=baseline,
    )


RUNS = [
    _run(
        1,
        RunStatus.verified,
        [FailureClass.needs_interaction, FailureClass.popup_overlay, None],
        9,
        15,
    ),
    _run(2, RunStatus.verified, [None], 4, 12),
    _run(3, RunStatus.unrecoverable, [FailureClass.captcha], 3, 9),
    _run(4, RunStatus.budget_exhausted, [FailureClass.misread_page] * 4, 40, None),
    _run(5, RunStatus.cancelled, [], 1, None),
    _run(6, RunStatus.running, [], 0, None),
    _run(7, RunStatus.verified, [FailureClass.bot_block, None], 6, 30, mode=RunMode.replay),
]


def test_live_totals_exclude_replays_and_cancelled_runs():
    s = compute_stats(RUNS)
    assert (s.runs_total, s.runs_finished) == (6, 5)
    assert (s.diagnosed, s.fixed, s.verified_first_try) == (3, 1, 1)
    assert (s.unrecoverable, s.budget_exhausted, s.errors) == (1, 1, 0)
    assert s.credits_used_total == 9 + 4 + 3 + 40
    assert s.baseline_credits_total == 15 + 12 + 9
    assert s.credits_saved == (15 + 12 + 9) - (9 + 4 + 3)
    assert s.by_class[FailureClass.misread_page] == 4
    assert s.by_class[FailureClass.auth_wall] == 0
    assert [r.run_id for r in s.rows] == ["r6", "r5", "r4", "r3", "r2", "r1"]
    assert s.rows[-1].classes == [FailureClass.needs_interaction, FailureClass.popup_overlay]


def test_including_replays():
    s = compute_stats(RUNS, include_replay=True)
    assert s.include_replay and s.runs_total == 7 and s.fixed == 2
    assert s.rows[0].mode is RunMode.replay


def test_no_runs():
    s = compute_stats([])
    assert s.runs_total == 0 and s.credits_saved == 0 and s.rows == []
