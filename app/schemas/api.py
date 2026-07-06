"""Modèles requête/réponse des endpoints FastAPI."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.actions import InfeasibilityReport
from app.schemas.ir import Strength
from app.schemas.schedule import Schedule, ScheduleDiff


class SessionCreateRequest(BaseModel):
    horizon_start: Optional[date] = None  # défaut : aujourd'hui


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class ChatTurn(BaseModel):
    who: str  # "user" | "assistant"
    text: str


class ConstraintView(BaseModel):
    id: str
    type: str
    label: str
    summary: str
    strength: Strength
    weight: int
    is_default: bool
    active: bool
    source_request_id: str


class SessionView(BaseModel):
    session_id: str
    horizon_start: date
    horizon_end: date
    timezone: str
    solver_status: str
    schedule: Optional[Schedule] = None
    constraints: list[ConstraintView] = Field(default_factory=list)
    chat_history: list[ChatTurn] = Field(default_factory=list)
    infeasibility: Optional[InfeasibilityReport] = None
    validated_at: Optional[datetime] = None


class ChatResponse(BaseModel):
    assistant_message: str
    solver_status: str
    schedule: Optional[Schedule] = None
    diff: ScheduleDiff = Field(default_factory=ScheduleDiff)
    infeasibility: Optional[InfeasibilityReport] = None
    constraints: list[ConstraintView] = Field(default_factory=list)
