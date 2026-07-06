"""Parseur NL -> ParseResult : construction du contexte et appel Gemini."""
from __future__ import annotations

from datetime import date

from app.compiler.timegrid import TimeGrid
from app.llm.client import GeminiClient
from app.llm.prompts import PARSER_SYSTEM, parser_user_prompt
from app.schemas.actions import ParseResult
from app.schemas.ir import (
    AnyConstraint,
    Blackout,
    BufferRule,
    FixedEvent,
    FlexibleTask,
    MaxStretch,
    RecurringBudget,
    Strength,
)


def summarize_constraint(c: AnyConstraint) -> str:
    s = "hard" if c.strength == Strength.HARD else f"soft(w={c.weight})"
    if isinstance(c, FixedEvent):
        rec = c.recurrence
        when = (
            f"once {rec.on_date}" if rec.freq == "ONCE"
            else f"{rec.freq.lower()} {','.join(w.value for w in rec.weekdays) or 'all days'}"
        )
        return f"{when} at {c.start_time}, {c.duration_minutes}min, {c.category.value}, {s}"
    if isinstance(c, FlexibleTask):
        parts = [f"{c.duration_minutes}min {c.category.value}"]
        if c.earliest:
            parts.append(f"from {c.earliest}")
        if c.deadline:
            parts.append(f"by {c.deadline}")
        if c.splittable:
            parts.append(f"splittable>={c.min_chunk_minutes}min")
        return ", ".join(parts) + f", {s}"
    if isinstance(c, RecurringBudget):
        parts = [f"{c.total_minutes}min/{c.period.lower()} {c.category.value}"]
        if c.occurrences:
            parts.append(f"{c.occurrences}x")
        if c.chunk_minutes:
            parts.append(f"chunks of {c.chunk_minutes}min")
        if c.required_window:
            parts.append(f"required {c.required_window.start}-{c.required_window.end}")
        if c.preferred_window:
            parts.append(f"preferred {c.preferred_window.start}-{c.preferred_window.end}")
        return ", ".join(parts) + f", {s}"
    if isinstance(c, Blackout):
        wins = ",".join(f"{w.start}-{w.end}" for w in c.windows) or "all day"
        days = ",".join(w.value for w in c.weekdays) or "all days"
        cats = ",".join(a.value for a in c.applies_to) or "everything"
        return f"forbidden {wins} on {days} for {cats}, {s}"
    if isinstance(c, BufferRule):
        return f"{c.minutes}min buffer around located events, {s}"
    if isinstance(c, MaxStretch):
        return f"max {c.max_minutes}min of {c.category.value} in a row, gap {c.min_gap_minutes}min, {s}"
    return s


def constraint_table(constraints: list[AnyConstraint]) -> str:
    rows = []
    for c in constraints:
        if not c.active:
            continue
        flag = " [DEFAULT]" if c.is_default else ""
        kind = c.type.upper()
        rows.append(f"{c.id} | {kind}{flag} | {c.label} | {summarize_constraint(c)}")
    return "\n".join(rows)


def parse_message(
    client: GeminiClient,
    message: str,
    constraints: list[AnyConstraint],
    history: list[tuple[str, str]],
    grid: TimeGrid,
    today: date,
) -> ParseResult:
    user = parser_user_prompt(
        today_str=today.isoformat(),
        tz_name=str(grid.tz),
        horizon_start=grid.start_date.isoformat(),
        horizon_end=grid.end_date.isoformat(),
        constraint_table=constraint_table(constraints),
        history=history,
        message=message,
    )
    return client.structured(PARSER_SYSTEM, user, ParseResult)
