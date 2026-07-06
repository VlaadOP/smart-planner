from datetime import date

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


def meeting_tuesday(rid="r-meet"):
    return FixedEvent(
        source_request_id=rid,
        label="Réunion équipe",
        recurrence=Recurrence(freq="WEEKLY", weekdays=[Weekday.TUE]),
        start_time="14:00",
        duration_minutes=60,
    )


def test_fixed_event_expansion(grid):
    cm = compile_constraints([meeting_tuesday()], grid)
    assert len(cm.chunks) == 5  # mardis des jours 1, 8, 15, 22, 29
    starts = sorted(c.fixed_start for c in cm.chunks)
    assert starts == [d * 96 + 56 for d in (1, 8, 15, 22, 29)]
    assert all(c.required_presence for c in cm.chunks)
    assert cm.hard_request_ids == {"r-meet"}


def test_daily_budget_chunks(grid):
    budget = RecurringBudget(
        source_request_id="r-break",
        label="Pause quotidienne",
        category=ActivityCategory.BREAK,
        period="DAY",
        total_minutes=60,
        min_chunk_minutes=15,
    )
    cm = compile_constraints([budget], grid)
    assert len(cm.groups) == 30
    assert all(g.target_slots == 4 for g in cm.groups)
    # cap anti-explosion : au plus 4 chunks par période
    assert len(cm.chunks) == 30 * 4


def test_sleep_last_night_skipped(grid):
    # La fenêtre de sommeil de la dernière nuit dépasse l'horizon (tronquée
    # à < 8h) : la période est sautée au lieu de créer une infaisabilité.
    sleep = next(c for c in default_constraints() if c.id == "def-sleep")
    cm = compile_constraints([sleep], grid)
    assert len(cm.groups) == 29


def test_chunk_keys_stable(grid):
    constraints = [
        meeting_tuesday(),
        FlexibleTask(
            id="task1",
            source_request_id="r-task",
            label="Rapport",
            duration_minutes=180,
            deadline=date(2026, 7, 10),
        ),
    ]
    keys1 = [c.key for c in compile_constraints(constraints, grid).chunks]
    keys2 = [c.key for c in compile_constraints(constraints, grid).chunks]
    assert keys1 == keys2


def test_splittable_task(grid):
    task = FlexibleTask(
        source_request_id="r-task",
        label="Étude",
        duration_minutes=240,
        splittable=True,
        min_chunk_minutes=60,
    )
    cm = compile_constraints([task], grid)
    assert len(cm.chunks) == 4
    assert len(cm.groups) == 1
    assert cm.groups[0].target_slots == 16
