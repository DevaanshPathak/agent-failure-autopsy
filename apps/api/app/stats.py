"""Results-page numbers (pure). Credits are estimates: 1 per agent step (ADR-004)."""

from collections import Counter

from app.models import (
    VERDICT_STATUSES,
    FailureClass,
    Run,
    RunMode,
    RunStatus,
    Stats,
    StatsRow,
)

MAX_ROWS = 200


def _classes(run: Run) -> list[FailureClass]:
    return [a.diagnosis.failure_class for a in run.attempts if a.diagnosis is not None]


def compute_stats(runs: list[Run], include_replay: bool = False) -> Stats:
    """Totals over finished runs (cancelled runs only count towards runs_total/runs_finished).

    Replays are excluded unless asked for, so a replay never double-counts the live run it was
    recorded from. `credits_saved` compares only runs that have a baseline estimate.
    """
    selected = [r for r in runs if include_replay or r.mode is RunMode.live]
    finished = [r for r in selected if r.status in VERDICT_STATUSES]
    counted = [r for r in finished if r.status is not RunStatus.cancelled]

    def with_status(status: RunStatus) -> list[Run]:
        return [r for r in counted if r.status is status]

    verified = with_status(RunStatus.verified)
    with_baseline = [r for r in counted if r.baseline_credits_estimate is not None]
    baseline_total = sum(r.baseline_credits_estimate or 0 for r in with_baseline)
    by_class = Counter(c for r in counted for c in _classes(r))

    rows = [
        StatsRow(
            run_id=r.id,
            created_at=r.created_at,
            site_id=r.request.site_id,
            url=r.request.url,
            mode=r.mode,
            status=r.status,
            attempts=len(r.attempts),
            credits_used=r.credits_used,
            baseline_credits_estimate=r.baseline_credits_estimate,
            classes=_classes(r),
        )
        for r in sorted(selected, key=lambda r: r.created_at, reverse=True)[:MAX_ROWS]
    ]
    return Stats(
        include_replay=include_replay,
        runs_total=len(selected),
        runs_finished=len(finished),
        diagnosed=sum(1 for r in counted if _classes(r)),
        fixed=sum(1 for r in verified if _classes(r)),
        verified_first_try=sum(1 for r in verified if not _classes(r)),
        unrecoverable=len(with_status(RunStatus.unrecoverable)),
        budget_exhausted=len(with_status(RunStatus.budget_exhausted)),
        errors=len(with_status(RunStatus.error)),
        credits_used_total=sum(r.credits_used for r in counted),
        baseline_credits_total=baseline_total,
        credits_saved=baseline_total - sum(r.credits_used for r in with_baseline),
        by_class={cls: by_class.get(cls, 0) for cls in FailureClass},
        rows=rows,
    )
