"""Round-trip .ics : export -> re-parse icalendar -> mêmes événements/horaires."""
from datetime import datetime
from zoneinfo import ZoneInfo

from icalendar import Calendar

from app.export.ics import IcsExporter
from app.schemas.ir import ActivityCategory
from app.schemas.schedule import Schedule, ScheduledBlock

TZ = ZoneInfo("Asia/Tokyo")


def block(key: str, label: str, start: datetime, end: datetime, is_default=False) -> ScheduledBlock:
    return ScheduledBlock(
        key=key,
        constraint_id=key.split(":")[0],
        source_request_id="r1",
        label=label,
        category=ActivityCategory.MEETING,
        start=start,
        end=end,
        is_default=is_default,
    )


def test_ics_roundtrip():
    schedule = Schedule(
        blocks=[
            block("m1:d1", "Réunion équipe", datetime(2026, 7, 7, 14, 0, tzinfo=TZ), datetime(2026, 7, 7, 15, 0, tzinfo=TZ)),
            block("m1:d8", "Réunion équipe", datetime(2026, 7, 14, 14, 0, tzinfo=TZ), datetime(2026, 7, 14, 15, 0, tzinfo=TZ)),
            block("def:s", "Sommeil", datetime(2026, 7, 7, 23, 0, tzinfo=TZ), datetime(2026, 7, 8, 7, 0, tzinfo=TZ), is_default=True),
        ],
        solver_status="OPTIMAL",
    )
    payload = IcsExporter().export(schedule, session_id="sess1", include_defaults=False)
    cal = Calendar.from_ical(payload)
    events = [c for c in cal.walk() if c.name == "VEVENT"]
    assert len(events) == 2  # les blocs par défaut sont exclus
    ev = events[0]
    assert str(ev["summary"]) == "Réunion équipe"
    assert ev["uid"] == "sess1-m1:d1@smart-planner"
    assert ev["dtstart"].dt == datetime(2026, 7, 7, 14, 0, tzinfo=TZ)
    assert ev["dtend"].dt == datetime(2026, 7, 7, 15, 0, tzinfo=TZ)

    # UIDs déterministes : un ré-export produit les mêmes identifiants
    payload2 = IcsExporter().export(schedule, session_id="sess1", include_defaults=False)
    assert payload == payload2

    # include_defaults=True exporte aussi le sommeil
    all_events = Calendar.from_ical(IcsExporter().export(schedule, "sess1", include_defaults=True))
    assert len([c for c in all_events.walk() if c.name == "VEVENT"]) == 3
