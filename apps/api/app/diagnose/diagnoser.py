"""Diagnosis orchestration: rules first, Claude when the rules are unsure, rules as the fallback."""

from typing import Any

from app.diagnose.llm import DiagnoseContext, diagnose_with_llm, evidence_sources
from app.diagnose.rules import classify, explain
from app.llm.claude import ClaudeClient
from app.models import (
    RECOVERABLE,
    Attempt,
    Diagnosis,
    DiagnosisSource,
    Evidence,
    EvidenceSource,
    FailureClass,
    FetchExtraction,
    LlmDiagnosis,
    Rung,
    TraceEvent,
    VerifyResult,
)
from app.patch.planner import PlanContext, plan
from app.verify.verifier import cut

FALLBACK_CONFIDENCE = 0.4


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _verified_quotes(llm: LlmDiagnosis, ctx: DiagnoseContext) -> list[Evidence]:
    """Keep only quotes that appear verbatim (whitespace/case-insensitive) in what Claude saw."""
    sources = [(source, _norm(text), seq) for source, text, seq in evidence_sources(ctx)]
    evidence: list[Evidence] = []
    for quote in llm.evidence_quotes:
        needle = _norm(quote)
        if not needle:
            continue
        match = next(((src, seq) for src, text, seq in sources if needle in text), None)
        if match:
            evidence.append(Evidence(source=match[0], quote=cut(quote, 300), event_seq=match[1]))
        if len(evidence) == 3:
            break
    return evidence


def _label_of(trace: list[TraceEvent], seq: int | None) -> str | None:
    return next((ev.label for ev in trace if ev.seq == seq), None) if seq is not None else None


async def diagnose(
    *,
    attempt: Attempt,
    vr: VerifyResult,
    trace: list[TraceEvent],
    fetch: dict[str, Any] | None,
    fetch_text: str | None,
    extraction: FetchExtraction | None,
    history: list[Diagnosis],
    plan_ctx: PlanContext,
    claude: ClaudeClient | None,
    threshold: float,
    goal: str,
    url: str,
) -> Diagnosis:
    rule = classify(attempt, vr, trace, history, extraction, fetch)
    seqs = {ev.seq for ev in trace}

    failure_class: FailureClass
    source: DiagnosisSource
    llm_prefix = llm_suffix = ""
    if rule.failure_class is not None and rule.confidence >= threshold:
        failure_class, source = rule.failure_class, DiagnosisSource.rules
        confidence, step_seq = rule.confidence, rule.failing_step_seq
        evidence, explanation = rule.evidence, rule.explanation
    else:
        llm_error: str | None = "ANTHROPIC_API_KEY is not set"
        llm: LlmDiagnosis | None = None
        ctx = DiagnoseContext(
            goal=goal,
            url=url,
            attempt=attempt,
            verify=vr,
            trace=trace,
            fetch_text=fetch_text,
            extraction=extraction,
            rule=rule,
            history=history,
        )
        if claude is not None:
            outcome = await diagnose_with_llm(claude, ctx)
            llm, llm_error = outcome.parsed, outcome.error
        if llm is not None:
            failure_class, source = llm.failure_class, DiagnosisSource.llm
            confidence = min(1.0, max(0.0, llm.confidence))
            step_seq = (
                llm.failing_step_seq if llm.failing_step_seq in seqs else rule.failing_step_seq
            )
            evidence = _verified_quotes(llm, ctx) or rule.evidence
            explanation = llm.explanation.strip() or explain(failure_class)
            llm_prefix, llm_suffix = llm.suggested_goal_prefix, llm.suggested_goal_suffix
        else:
            default = (
                FailureClass.needs_interaction
                if attempt.rung is Rung.fetch
                else FailureClass.misread_page
            )
            failure_class = rule.failure_class or default
            source = DiagnosisSource.rules_fallback
            confidence = rule.confidence if rule.failure_class else FALLBACK_CONFIDENCE
            step_seq = rule.failing_step_seq
            evidence = rule.evidence
            explanation = rule.explanation or explain(failure_class)
            if claude is not None:
                explanation += f" (automatic diagnosis unavailable: {llm_error})"

    if not evidence:
        evidence = [Evidence(source=EvidenceSource.verifier, quote=cut(vr.summary, 300))]
    patch = plan(failure_class, plan_ctx, llm_prefix, llm_suffix)
    return Diagnosis(
        attempt_no=attempt.attempt_no,
        failure_class=failure_class,
        recoverable=failure_class in RECOVERABLE,
        confidence=confidence,
        failing_step_seq=step_seq,
        failing_step_label=_label_of(trace, step_seq),
        evidence=evidence[:5],
        explanation=explanation,
        patch=patch,
        source=source,
    )
