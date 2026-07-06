"""État de session + persistance JSON atomique (un fichier par session)."""
from __future__ import annotations

import os
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from app.schemas.actions import InfeasibilityReport
from app.schemas.api import ChatTurn
from app.schemas.ir import AnyConstraint
from app.schemas.schedule import Schedule, SolvedChunk


class SessionState(BaseModel):
    session_id: str
    horizon_start: date
    horizon_days: int
    timezone: str
    constraints: list[AnyConstraint] = Field(default_factory=list)
    request_log: dict[str, str] = Field(default_factory=dict)  # request_id -> énoncé
    chat_history: list[ChatTurn] = Field(default_factory=list)
    last_solution: dict[str, SolvedChunk] = Field(default_factory=dict)
    last_good_schedule: Optional[Schedule] = None
    solver_status: str = "UNKNOWN"
    last_infeasibility: Optional[InfeasibilityReport] = None
    validated_at: Optional[datetime] = None
    request_counter: int = 0

    def new_request_id(self, utterance: str) -> str:
        self.request_counter += 1
        rid = f"req-{self.request_counter:03d}"
        self.request_log[rid] = utterance
        return rid


class SessionStore:
    """Sessions en mémoire, écrites atomiquement sur disque à chaque mutation."""

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, SessionState] = {}

    def _path(self, session_id: str) -> Path:
        return self.root / session_id / "store.json"

    def create(self, horizon_start: date, horizon_days: int, timezone: str) -> SessionState:
        state = SessionState(
            session_id=uuid4().hex[:10],
            horizon_start=horizon_start,
            horizon_days=horizon_days,
            timezone=timezone,
        )
        self._cache[state.session_id] = state
        self.save(state)
        return state

    def get(self, session_id: str) -> SessionState | None:
        if session_id in self._cache:
            return self._cache[session_id]
        path = self._path(session_id)
        if path.exists():
            state = SessionState.model_validate_json(path.read_text(encoding="utf-8"))
            self._cache[session_id] = state
            return state
        return None

    def save(self, state: SessionState) -> None:
        path = self._path(state.session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = state.model_dump_json(indent=2)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
