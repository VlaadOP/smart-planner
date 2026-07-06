"""Planning résolu (wall-clock, prêt pour le frontend et l'export)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.ir import ActivityCategory


class ScheduledBlock(BaseModel):
    key: str  # clé stable du chunk (constraint_id + occurrence) — sert au diff/stabilité
    constraint_id: str
    source_request_id: str
    label: str
    category: ActivityCategory
    start: datetime  # tz-aware
    end: datetime  # tz-aware, hors tampon trajet
    is_default: bool = False


class Schedule(BaseModel):
    blocks: list[ScheduledBlock] = Field(default_factory=list)
    solver_status: str = "UNKNOWN"
    objective: Optional[float] = None


class SolvedChunk(BaseModel):
    """État brut d'un chunk après solve (unités slots) — persisté pour la stabilité."""

    key: str
    start: int
    size: int
    present: bool


class ScheduleDiff(BaseModel):
    added: list[str] = Field(default_factory=list)  # clés de blocs
    removed: list[str] = Field(default_factory=list)
    moved: list[str] = Field(default_factory=list)


def diff_schedules(prev: Schedule | None, new: Schedule) -> ScheduleDiff:
    prev_by_key = {b.key: b for b in (prev.blocks if prev else [])}
    new_by_key = {b.key: b for b in new.blocks}
    added = [k for k in new_by_key if k not in prev_by_key]
    removed = [k for k in prev_by_key if k not in new_by_key]
    moved = [
        k
        for k, b in new_by_key.items()
        if k in prev_by_key and (prev_by_key[k].start != b.start or prev_by_key[k].end != b.end)
    ]
    return ScheduleDiff(added=added, removed=removed, moved=moved)
