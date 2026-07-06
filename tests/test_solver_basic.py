from datetime import date, time

from app.compiler.compile import compile_constraints
from app.defaults.realism import default_constraints
from app.schemas.ir import (
    ActivityCategory,
    FixedEvent,
    FlexibleTask,
    Recurrence,
    RecurringBudget,
    Weekday,
)
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


def test_weekly_sessions_spread_across_days(grid, cfg):
    # "3x45 min de sport par semaine" ne doit pas atterrir 3x le même jour ni
    # en pleine nuit (régression : tout était empilé le lundi à 00:00).
    sport = RecurringBudget(
        id="sport",
        source_request_id="r-sport",
        label="Sport",
        category=ActivityCategory.SPORT,
        period="WEEK",
        total_minutes=135,
        occurrences=3,
        chunk_minutes=45,
    )
    cm = compile_constraints(default_constraints() + [sport], grid)
    outcome = run_solve(cm, grid, cfg)
    assert outcome.status in ("OPTIMAL", "FEASIBLE")
    assert validate_schedule(outcome.schedule, cm, grid) == []

    blocks = [b for b in outcome.schedule.blocks if b.constraint_id == "sport"]
    # Première semaine (jours 0-6) : 3 séances sur 3 dates distinctes, hors nuit.
    week1 = [b for b in blocks if (b.start.date() - date(2026, 7, 6)).days < 7]
    assert len(week1) == 3
    assert len({b.start.date() for b in week1}) == 3
    assert all(b.start.time() >= time(7, 0) for b in week1)


def test_awake_activities_avoid_deep_night(grid, cfg):
    # Régression : pauses (BREAK) et tâches génériques (OTHER) atterrissaient à
    # 00:00 car le repos nocturne ne couvrait que work/meeting/sport/perso.
    extra = [
        RecurringBudget(
            id="pause",
            source_request_id="r-pause",
            label="Pause",
            category=ActivityCategory.BREAK,
            period="DAY",
            total_minutes=60,
            min_chunk_minutes=15,
        ),
        FlexibleTask(
            id="divers",
            source_request_id="r-divers",
            label="Projet divers",
            category=ActivityCategory.OTHER,
            duration_minutes=480,
            splittable=True,
            min_chunk_minutes=120,
            deadline=date(2026, 7, 12),
        ),
    ]
    cm = compile_constraints(default_constraints() + extra, grid)
    outcome = run_solve(cm, grid, cfg)
    assert outcome.status in ("OPTIMAL", "FEASIBLE")
    assert validate_schedule(outcome.schedule, cm, grid) == []
    awake = [b for b in outcome.schedule.blocks if b.constraint_id in {"pause", "divers"}]
    assert awake  # les blocs existent bien
    assert all(b.start.time() >= time(6, 0) for b in awake)


def test_realism_defaults_present(grid, cfg):
    cm = compile_constraints(default_constraints(), grid)
    outcome = run_solve(cm, grid, cfg)
    assert outcome.status in ("OPTIMAL", "FEASIBLE")
    blocks = outcome.schedule.blocks
    sleep_days = {b.start.date() for b in blocks if b.constraint_id == "def-sleep"}
    assert len(sleep_days) >= 28  # une nuit de sommeil (presque) chaque jour
    lunches = [b for b in blocks if b.constraint_id == "def-lunch"]
    assert len(lunches) == 30
