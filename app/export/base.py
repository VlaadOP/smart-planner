"""Interface d'export : .ics aujourd'hui, Google Calendar API demain."""
from __future__ import annotations

from typing import Protocol

from app.schemas.schedule import Schedule


class Exporter(Protocol):
    def export(self, schedule: Schedule, session_id: str, include_defaults: bool = False) -> bytes: ...
