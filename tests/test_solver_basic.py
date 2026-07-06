from datetime import date, time

from app.compiler.compile import compile_constraints
from app.defaults.realism import default_constraints
from app.schemas.ir import FixedEvent, FlexibleTask, Recurrence, Weekday
from app.solver.solve import run_solve
from app.solver.validate import validate_schedule


def build_fixture():
    return default_constraints() + [
        FixedEvent(
            id="meet1",
            source_request_id="r-meet",
            label="Réunion équipe",
            recurrence=Recurrence(freq="WEEKLY", weekdays=[Weekday.TUE]),
            start_time="14:00",
            duration_minutes=60,
        ),
        FlexibleTask(
            id="task1",
            source_request_id="r-task",
            label="Rapport",
            duration_minutes=180,
            deadline=date(2026, 7, 10),
        ),
    ]


def test_basic_schedule_valid(grid, cfg):
    constraints = build_fixture()
    cm = compile_constraints(constraints, grid)
    outcome = run_solve(cm, grid, cfg)
    assert outcome.status in ("OPTIMAL", "FEASIBLE")
    schedule = outcome.schedule
    assert schedule is not None

    # Validation par un vérificateur indépendant du solveur
    assert validate_schedule(schedule, cm, grid) == []

    # La réunion hebdo est présente chaque mardi à 14:00
    meetings = [b for b in schedule.blocks if b.constraint_id == "meet1"]
    assert len(meetings) == 5
    assert all(b.start.time() == time(14, 0) and b.start.weekday() == 1 for b in meetings)

    # La tâche est planifiée avant sa deadline (fin du 2026-07-10)
    tasks = [b for b in schedule.blocks if b.constraint_id == "task1"]
    assert sum((b.end - b.start).total_seconds() for b in tasks) == 180 * 60
    assert all(b.end.date() <= date(2026, 7, 11) for b in tasks)


def test_determinism(grid, cfg):
    constraints = build_fixture()
    cm = compile_constraints(constraints, grid)
    s1 = run_solve(cm, grid, cfg).schedule
    s2 = run_solve(cm, grid, cfg).schedule
    assert [(b.key, b.start, b.end) for b in s1.blocks] == [(b.key, b.start, b.end) for b in s2.blocks]


def test_realism_defaults_present(grid, cfg):
    cm = compile_constraints(default_constraints(), grid)
    outcome = run_solve(cm, grid, cfg)
    assert outcome.status in ("OPTIMAL", "FEASIBLE")
    blocks = outcome.schedule.blocks
    sleep_days = {b.start.date() for b in blocks if b.constraint_id == "def-sleep"}
    assert len(sleep_days) >= 28  # une nuit de sommeil (presque) chaque jour
    lunches = [b for b in blocks if b.constraint_id == "def-lunch"]
    assert len(lunches) == 30
