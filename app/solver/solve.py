"""Orchestration de la résolution : solve normal, extraction du planning,
et bascule vers l'extraction de cœur unsat en cas d'infaisabilité."""
from __future__ import annotations

from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from app.compiler.compile import CompiledModel
from app.compiler.timegrid import TimeGrid
from app.config import Settings
from app.schemas.schedule import Schedule, ScheduledBlock, SolvedChunk
from app.solver.model import BuiltModel, build_model
from app.solver.unsat import find_core

_STATUS_NAMES = {
    cp_model.OPTIMAL: "OPTIMAL",
    cp_model.FEASIBLE: "FEASIBLE",
    cp_model.INFEASIBLE: "INFEASIBLE",
    cp_model.MODEL_INVALID: "MODEL_INVALID",
    cp_model.UNKNOWN: "UNKNOWN",
}


@dataclass
class SolveOutcome:
    status: str
    schedule: Schedule | None = None
    solution: dict[str, SolvedChunk] = field(default_factory=dict)
    core_request_ids: list[str] = field(default_factory=list)
    objective: float | None = None


def make_solver(cfg: Settings, time_limit: float | None = None) -> cp_model.CpSolver:
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit or cfg.solver_time_limit_s
    solver.parameters.num_search_workers = cfg.solver_workers
    solver.parameters.random_seed = cfg.solver_seed
    return solver


def extract_schedule(built: BuiltModel, solver: cp_model.CpSolver, grid: TimeGrid, status: str) -> tuple[Schedule, dict[str, SolvedChunk]]:
    blocks: list[ScheduledBlock] = []
    solution: dict[str, SolvedChunk] = {}
    for key, cv in built.chunk_vars.items():
        present = bool(solver.Value(cv.presence))
        start = int(solver.Value(cv.start))
        size = int(solver.Value(cv.size))
        solution[key] = SolvedChunk(key=key, start=start, size=size, present=present)
        if present:
            blocks.append(
                ScheduledBlock(
                    key=key,
                    constraint_id=cv.spec.constraint_id,
                    source_request_id=cv.spec.source_request_id,
                    label=cv.spec.label,
                    category=cv.spec.category,
                    start=grid.slot_to_datetime(start),
                    end=grid.slot_to_datetime(start + size),
                    is_default=cv.spec.is_default,
                )
            )
    blocks.sort(key=lambda b: b.start)
    objective = solver.ObjectiveValue() if built.has_objective else None
    return Schedule(blocks=blocks, solver_status=status, objective=objective), solution


def run_solve(
    cm: CompiledModel,
    grid: TimeGrid,
    cfg: Settings,
    prev: dict[str, SolvedChunk] | None = None,
) -> SolveOutcome:
    built = build_model(cm, cfg, prev=prev, enforced=None)
    solver = make_solver(cfg)
    status_code = solver.Solve(built.model)
    status = _STATUS_NAMES.get(status_code, str(status_code))

    if status in ("OPTIMAL", "FEASIBLE"):
        schedule, solution = extract_schedule(built, solver, grid, status)
        return SolveOutcome(
            status=status, schedule=schedule, solution=solution, objective=schedule.objective
        )

    if status == "INFEASIBLE":
        core = find_core(cm, cfg)
        return SolveOutcome(status=status, core_request_ids=core)

    # UNKNOWN / MODEL_INVALID : pas de solution exploitable, pas de crash.
    return SolveOutcome(status=status)
