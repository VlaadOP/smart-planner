"""Export .ics (icalendar). Un VEVENT par bloc, UIDs déterministes pour que les
ré-imports mettent à jour au lieu de dupliquer. Les récurrences ont déjà été
expansées en occurrences — pas de reconstruction de RRULE."""
from __future__ import annotations

from icalendar import Calendar, Event

from app.schemas.schedule import Schedule

PRODID = "-//smart-planner//FR"


class IcsExporter:
    def export(self, schedule: Schedule, session_id: str, include_defaults: bool = False) -> bytes:
        cal = Calendar()
        cal.add("prodid", PRODID)
        cal.add("version", "2.0")
        cal.add("calscale", "GREGORIAN")
        for block in schedule.blocks:
            if block.is_default and not include_defaults:
                continue
            ev = Event()
            ev.add("uid", f"{session_id}-{block.key}@smart-planner")
            ev.add("summary", block.label)
            ev.add("dtstart", block.start)
            ev.add("dtend", block.end)
            ev.add("categories", [block.category.value])
            cal.add_component(ev)
        return cal.to_ical()
