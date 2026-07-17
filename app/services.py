"""Orchestration : compile -> solve -> diff -> état de session.

C'est le chemin unique emprunté par le chat, la suppression de contrainte et
l'acceptation d'une relaxation. En cas d'infaisabilité, le dernier planning
faisable est conservé et un rapport de conflit est produit (LLM si disponible,
repli déterministe sinon) — le système ne crashe jamais.
"""
from __future__ import annotations

from typing import Callable, Optional
from zoneinfo import ZoneInfo

from app.compiler.compile import CompiledModel, ModelTooLargeError, compile_constraints
from app.compiler.timegrid import TimeGrid
from app.config import Settings
from app.llm.parser import summarize_constraint
from app.schemas.actions import InfeasibilityReport
from app.schemas.api import ConstraintView
from app.schemas.schedule import ScheduleDiff, diff_schedules
from app.solver.solve import run_solve
from app.store.session import SessionState

# Signature d'un explainer : (state, core_request_ids, compiled) -> rapport
ExplainFn = Callable[[SessionState, list[str], CompiledModel], InfeasibilityReport]


def grid_for(state: SessionState) -> TimeGrid:
    return TimeGrid(state.horizon_start, state.horizon_days, ZoneInfo(state.timezone))


def constraint_views(state: SessionState) -> list[ConstraintView]:
    return [
        ConstraintView(
            id=c.id,
            type=c.type,
            label=c.label,
            summary=summarize_constraint(c),
            strength=c.strength,
            weight=c.weight,
            is_default=c.is_default,
            active=c.active,
            source_request_id=c.source_request_id,
        )
        for c in state.constraints
        if c.active
    ]


def fallback_explanation(state: SessionState, core: list[str], cm: CompiledModel) -> InfeasibilityReport:
    """Explication déterministe (sans LLM) : liste les requêtes en conflit."""
    lines = []
    for rid in core:
        utterance = state.request_log.get(rid)
        labels = ", ".join(cm.request_labels.get(rid, [])) or rid
        lines.append(f"“{utterance}” ({labels})" if utterance else labels)
    explanation = (
        "These requests are incompatible with each other: " + "; ".join(lines) + ". "
        "Relax or remove one of them to unblock the schedule."
    )
    return InfeasibilityReport(explanation=explanation, conflicting_request_ids=core, proposals=[])


def resolve(
    state: SessionState,
    cfg: Settings,
    explain: Optional[ExplainFn] = None,
) -> tuple[str, ScheduleDiff]:
    """Re-résout le planning et met à jour l'état. Retourne (status, diff)."""
    grid = grid_for(state)
    try:
        cm = compile_constraints(state.constraints, grid, max_chunks=cfg.max_chunks)
    except ModelTooLargeError as e:
        state.solver_status = "TOO_LARGE"
        state.last_infeasibility = InfeasibilityReport(
            explanation=str(e), conflicting_request_ids=[], proposals=[]
        )
        return state.solver_status, ScheduleDiff()

    outcome = run_solve(cm, grid, cfg, prev=state.last_solution or None)
    state.solver_status = outcome.status

    if outcome.status in ("OPTIMAL", "FEASIBLE"):
        diff = diff_schedules(state.last_good_schedule, outcome.schedule)
        state.last_good_schedule = outcome.schedule
        state.last_solution = outcome.solution
        state.last_infeasibility = None
        return outcome.status, diff

    if outcome.status == "INFEASIBLE":
        explainer = explain or fallback_explanation
        try:
            report = explainer(state, outcome.core_request_ids, cm)
        except Exception:
            report = fallback_explanation(state, outcome.core_request_ids, cm)
        state.last_infeasibility = report
        return outcome.status, ScheduleDiff()

    # UNKNOWN / MODEL_INVALID : on garde le dernier planning faisable.
    state.last_infeasibility = InfeasibilityReport(
        explanation=(
            "The solver did not find a solution within the time limit. "
            "The last valid schedule is kept."
        ),
        conflicting_request_ids=[],
        proposals=[],
    )
    return outcome.status, ScheduleDiff()
