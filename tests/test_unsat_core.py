from datetime import date

from app.compiler.compile import compile_constraints
from app.defaults.realism import default_constraints
from app.schemas.ir import FixedEvent, Recurrence
from app.solver.solve import run_solve


def overlapping_events():
    common = dict(
        recurrence=Recurrence(freq="ONCE", on_date=date(2026, 7, 9)),
        start_time="14:00",
        duration_minutes=60,
    )
    return [
        FixedEvent(id="ev1", source_request_id="r1", label="Rendez-vous A", **common),
        FixedEvent(id="ev2", source_request_id="r2", label="Rendez-vous B", **common),
    ]


def test_unsat_core_names_exactly_the_conflict(grid, cfg):
    constraints = default_constraints() + overlapping_events()
    cm = compile_constraints(constraints, grid)
    outcome = run_solve(cm, grid, cfg)
    assert outcome.status == "INFEASIBLE"
    assert outcome.schedule is None
    # Le cœur désigne exactement les deux requêtes en conflit — pas les défauts.
    assert outcome.core_request_ids == ["r1", "r2"]


def test_feasible_after_removing_one(grid, cfg):
    constraints = default_constraints() + overlapping_events()[:1]
    cm = compile_constraints(constraints, grid)
    outcome = run_solve(cm, grid, cfg)
    assert outcome.status in ("OPTIMAL", "FEASIBLE")
