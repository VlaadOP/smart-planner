from datetime import date

from app.compiler.compile import compile_constraints
from app.defaults.realism import default_constraints
from app.schemas.ir import FixedEvent, FlexibleTask, Recurrence
from app.solver.solve import run_solve


def test_stability_on_incremental_change(grid, cfg):
    base = default_constraints() + [
        FlexibleTask(
            id="taskA",
            source_request_id="r-a",
            label="Tâche A",
            duration_minutes=120,
            deadline=date(2026, 7, 15),
        ),
    ]
    cm1 = compile_constraints(base, grid)
    out1 = run_solve(cm1, grid, cfg)
    assert out1.status in ("OPTIMAL", "FEASIBLE")

    # Ajout d'une contrainte : le reste du planning doit bouger le moins possible
    extended = base + [
        FixedEvent(
            id="meet2",
            source_request_id="r-b",
            label="Réunion",
            recurrence=Recurrence(freq="ONCE", on_date=date(2026, 7, 8)),
            start_time="10:00",
            duration_minutes=60,
        ),
    ]
    cm2 = compile_constraints(extended, grid)
    out2 = run_solve(cm2, grid, cfg, prev=out1.solution)
    assert out2.status in ("OPTIMAL", "FEASIBLE")

    prev_by_key = {b.key: b.start for b in out1.schedule.blocks}
    common = [b for b in out2.schedule.blocks if b.key in prev_by_key]
    unchanged = [b for b in common if prev_by_key[b.key] == b.start]
    assert len(common) > 0
    assert len(unchanged) / len(common) >= 0.9
