from datetime import date, datetime

from app.compiler.timegrid import SLOTS_PER_DAY, hhmm_to_offset, merge_ranges
from app.schemas.ir import Recurrence, TimeWindow, Weekday


def test_hhmm_to_offset():
    assert hhmm_to_offset("00:00") == 0
    assert hhmm_to_offset("14:30") == 58
    assert hhmm_to_offset("23:45") == 95


def test_slot_datetime_roundtrip(grid):
    for slot in (0, 1, 95, 96, 1500, grid.n_slots - 1):
        dt = grid.slot_to_datetime(slot)
        assert grid.datetime_to_slot(dt) == slot
    assert grid.slot_to_datetime(0) == datetime(2026, 7, 6, 0, 0, tzinfo=grid.tz)
    assert grid.slot_to_datetime(56) == datetime(2026, 7, 6, 14, 0, tzinfo=grid.tz)


def test_window_wrap_midnight(grid):
    # 22:00 -> 09:00 le lendemain
    r = grid.window_slot_range(0, TimeWindow(start="22:00", end="09:00"))
    assert r == (88, SLOTS_PER_DAY + 36)
    # end == start => 24 h
    r = grid.window_slot_range(0, TimeWindow(start="00:00", end="00:00"))
    assert r == (0, SLOTS_PER_DAY)
    # fenêtre du dernier jour clippée à l'horizon
    r = grid.window_slot_range(grid.days - 1, TimeWindow(start="22:00", end="09:00"))
    assert r == ((grid.days - 1) * SLOTS_PER_DAY + 88, grid.n_slots)


def test_recurrence_days(grid):
    assert grid.recurrence_days(Recurrence(freq="ONCE", on_date=date(2026, 7, 10))) == [4]
    assert grid.recurrence_days(Recurrence(freq="ONCE", on_date=date(2026, 9, 1))) == []
    assert grid.recurrence_days(Recurrence(freq="WEEKLY", weekdays=[Weekday.TUE])) == [1, 8, 15, 22, 29]
    assert grid.recurrence_days(Recurrence(freq="DAILY", until=date(2026, 7, 8))) == [0, 1, 2]


def test_merge_ranges():
    assert merge_ranges([(5, 10), (0, 3), (8, 12), (3, 4)]) == [(0, 4), (5, 12)]
    assert merge_ranges([]) == []
