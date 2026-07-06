"""Compilation de l'IR wall-clock en spécifications slot-space pour le solveur.

Sortie : un CompiledModel fait de ChunkSpec (intervalles candidats), GroupSpec
(sommes/comptes par contrainte), BlackoutSpec et MaxStretchSpec. Le solveur
(app/solver) ne voit que ces dataclasses — jamais l'IR ni Gemini.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.compiler.timegrid import (
    SLOTS_PER_DAY,
    TimeGrid,
    hhmm_to_offset,
    merge_ranges,
    minutes_to_slots,
)
from app.schemas.ir import (
    WEEKDAY_INDEX,
    ActivityCategory,
    AnyConstraint,
    Blackout,
    BufferRule,
    FixedEvent,
    FlexibleTask,
    MaxStretch,
    RecurringBudget,
    Strength,
)

MAX_CHUNKS_PER_PERIOD = 4  # cap anti-explosion pour les budgets/tâches fractionnables


class ModelTooLargeError(Exception):
    """Trop de tâches fractionnées pour construire un modèle raisonnable."""


@dataclass
class ChunkSpec:
    key: str  # stable entre deux solves (constraint_id + occurrence)
    constraint_id: str
    source_request_id: str
    label: str
    category: ActivityCategory
    is_default: bool
    strength: Strength
    weight: int
    min_size: int  # slots
    max_size: int
    fixed_start: int | None = None
    # L'intervalle (tampon inclus) doit tenir entièrement dans UNE de ces fenêtres.
    # None = tout l'horizon.
    windows: list[tuple[int, int]] | None = None
    # Présence exigée (événement fixe, tâche non fractionnée). Les chunks de
    # groupe ont required_presence=False : c'est la somme du groupe qui décide.
    required_presence: bool = False
    trailing_buffer: int = 0
    group_id: str | None = None
    preferred: list[tuple[int, int]] | None = None  # fenêtres préférées (soft, poids faible)


@dataclass
class GroupSpec:
    group_id: str
    constraint_id: str
    source_request_id: str
    label: str
    is_default: bool
    strength: Strength
    weight: int
    chunk_keys: list[str]
    target_slots: int | None = None  # somme des tailles présentes == target
    exact_count: int | None = None  # nombre de chunks présents == n
    ordered: bool = True  # chaîne anti-symétrie start_{i+1} >= end_i


@dataclass
class BlackoutSpec:
    constraint_id: str
    source_request_id: str
    label: str
    is_default: bool
    strength: Strength
    weight: int
    ranges: list[tuple[int, int]]
    categories: frozenset[ActivityCategory] | None  # None = toutes


@dataclass
class MaxStretchSpec:
    constraint_id: str
    source_request_id: str
    label: str
    is_default: bool
    strength: Strength
    weight: int
    category: ActivityCategory
    max_slots: int
    gap_slots: int


@dataclass
class CompiledModel:
    n_slots: int
    chunks: list[ChunkSpec] = field(default_factory=list)
    groups: list[GroupSpec] = field(default_factory=list)
    blackouts: list[BlackoutSpec] = field(default_factory=list)
    stretches: list[MaxStretchSpec] = field(default_factory=list)
    # Requêtes portant au moins une contrainte HARD -> littéral d'assomption
    hard_request_ids: set[str] = field(default_factory=set)
    request_labels: dict[str, list[str]] = field(default_factory=dict)


def _note_request(cm: CompiledModel, c: AnyConstraint) -> None:
    cm.request_labels.setdefault(c.source_request_id, [])
    if c.label not in cm.request_labels[c.source_request_id]:
        cm.request_labels[c.source_request_id].append(c.label)
    if c.strength == Strength.HARD:
        cm.hard_request_ids.add(c.source_request_id)


def _task_days(c: FlexibleTask, grid: TimeGrid) -> list[int]:
    first = 0 if c.earliest is None else max(0, grid.day_of_date(c.earliest))
    last = grid.days - 1 if c.deadline is None else min(grid.days - 1, grid.day_of_date(c.deadline))
    days = range(first, last + 1)
    if c.allowed_weekdays:
        allowed = {WEEKDAY_INDEX[wd] for wd in c.allowed_weekdays}
        return [d for d in days if grid.date_of_day(d).weekday() in allowed]
    return list(days)


def _day_windows(c_windows, day: int, grid: TimeGrid) -> list[tuple[int, int]]:
    if not c_windows:
        return [grid.day_range(day)]
    out = []
    for w in c_windows:
        r = grid.window_slot_range(day, w)
        if r:
            out.append(r)
    return out


def _compile_fixed_event(cm: CompiledModel, c: FixedEvent, grid: TimeGrid, buffer_slots: int) -> None:
    size = minutes_to_slots(c.duration_minutes)
    offset = hhmm_to_offset(c.start_time)
    buf = buffer_slots if c.location else 0
    for day in grid.recurrence_days(c.recurrence):
        start = day * SLOTS_PER_DAY + offset
        if start + size + buf > grid.n_slots:
            continue  # occurrence au-delà de l'horizon
        cm.chunks.append(
            ChunkSpec(
                key=f"{c.id}:d{day}",
                constraint_id=c.id,
                source_request_id=c.source_request_id,
                label=c.label,
                category=c.category,
                is_default=c.is_default,
                strength=c.strength,
                weight=c.weight,
                min_size=size,
                max_size=size,
                fixed_start=start,
                required_presence=True,
                trailing_buffer=buf,
            )
        )


def _compile_flexible_task(cm: CompiledModel, c: FlexibleTask, grid: TimeGrid, buffer_slots: int) -> None:
    dur = minutes_to_slots(c.duration_minutes)
    days = _task_days(c, grid)
    windows = merge_ranges([r for d in days for r in _day_windows(c.allowed_windows, d, grid)])
    if not windows:
        windows = [(0, 0)]  # aucune fenêtre possible -> insatisfiable si HARD (voulu)
    buf = buffer_slots if c.location else 0

    if not c.splittable:
        cm.chunks.append(
            ChunkSpec(
                key=f"{c.id}:c0",
                constraint_id=c.id,
                source_request_id=c.source_request_id,
                label=c.label,
                category=c.category,
                is_default=c.is_default,
                strength=c.strength,
                weight=c.weight,
                min_size=dur,
                max_size=dur,
                windows=windows,
                required_presence=True,
                trailing_buffer=buf,
            )
        )
        return

    min_chunk = min(minutes_to_slots(c.min_chunk_minutes), dur)
    max_chunk = minutes_to_slots(c.max_chunk_minutes) if c.max_chunk_minutes else dur
    max_chunk = min(max_chunk, dur)
    k = min(MAX_CHUNKS_PER_PERIOD, math.ceil(dur / min_chunk))
    if k * max_chunk < dur:
        # Même avec k chunks au max, la durée ne rentre pas : borne le fractionnement.
        k = min(MAX_CHUNKS_PER_PERIOD * 2, math.ceil(dur / max_chunk))
    keys = []
    for i in range(k):
        key = f"{c.id}:c{i}"
        keys.append(key)
        cm.chunks.append(
            ChunkSpec(
                key=key,
                constraint_id=c.id,
                source_request_id=c.source_request_id,
                label=c.label,
                category=c.category,
                is_default=c.is_default,
                strength=c.strength,
                weight=c.weight,
                min_size=min_chunk,
                max_size=max_chunk,
                windows=windows,
                trailing_buffer=buf,
                group_id=f"{c.id}:g",
            )
        )
    cm.groups.append(
        GroupSpec(
            group_id=f"{c.id}:g",
            constraint_id=c.id,
            source_request_id=c.source_request_id,
            label=c.label,
            is_default=c.is_default,
            strength=c.strength,
            weight=c.weight,
            chunk_keys=keys,
            target_slots=dur,
        )
    )


def _budget_periods(c: RecurringBudget, grid: TimeGrid) -> list[list[int]]:
    """Liste de périodes, chacune étant une liste d'indices de jours."""
    if c.period == "DAY":
        days = range(grid.days)
        if c.weekdays:
            allowed = {WEEKDAY_INDEX[wd] for wd in c.weekdays}
            days = [d for d in days if grid.date_of_day(d).weekday() in allowed]
        return [[d] for d in days]
    # WEEK : fenêtres consécutives de 7 jours depuis le début d'horizon
    periods = []
    for start in range(0, grid.days, 7):
        week = list(range(start, min(start + 7, grid.days)))
        if c.weekdays:
            allowed = {WEEKDAY_INDEX[wd] for wd in c.weekdays}
            week = [d for d in week if grid.date_of_day(d).weekday() in allowed]
        if week:
            periods.append(week)
    return periods


def _compile_budget(cm: CompiledModel, c: RecurringBudget, grid: TimeGrid) -> None:
    total = minutes_to_slots(c.total_minutes)
    chunk_size = minutes_to_slots(c.chunk_minutes) if c.chunk_minutes else None
    min_chunk = minutes_to_slots(c.min_chunk_minutes)
    if chunk_size:
        min_chunk = chunk_size

    for p_idx, days in enumerate(_budget_periods(c, grid)):
        # Prorata pour une dernière semaine partielle
        factor = 1.0 if c.period == "DAY" else min(1.0, len(days) / 7.0)
        p_total = math.floor(total * factor)
        if chunk_size:
            n = c.occurrences if c.occurrences else max(1, total // chunk_size)
            n = max(0, math.floor(n * factor))
            if n == 0:
                continue
            p_total = n * chunk_size
            k = n
            lo, hi = chunk_size, chunk_size
            exact_count = n
        else:
            p_total = (p_total // min_chunk) * min_chunk if p_total >= min_chunk else 0
            if p_total == 0:
                continue
            if c.occurrences:
                k = max(1, math.floor(c.occurrences * factor))
                exact_count = k
            else:
                k = min(MAX_CHUNKS_PER_PERIOD, math.ceil(p_total / min_chunk))
                exact_count = None
            lo, hi = min_chunk, p_total

        windows = merge_ranges(
            [
                r
                for d in days
                for r in _day_windows([c.required_window] if c.required_window else [], d, grid)
            ]
        )
        # Fenêtre tronquée par la fin d'horizon (ex. sommeil de la dernière nuit) :
        # si aucun chunk minimal ne peut y tenir, on saute la période plutôt que de
        # créer une pénalité/infaisabilité artificielle.
        windows = [w for w in windows if w[1] - w[0] >= lo]
        if not windows:
            continue
        preferred = None
        if c.preferred_window:
            preferred = merge_ranges(
                [r for d in days for r in _day_windows([c.preferred_window], d, grid)]
            )

        group_id = f"{c.id}:p{p_idx}"
        keys = []
        for i in range(k):
            key = f"{group_id}:c{i}"
            keys.append(key)
            cm.chunks.append(
                ChunkSpec(
                    key=key,
                    constraint_id=c.id,
                    source_request_id=c.source_request_id,
                    label=c.label,
                    category=c.category,
                    is_default=c.is_default,
                    strength=c.strength,
                    weight=c.weight,
                    min_size=lo,
                    max_size=hi,
                    windows=windows,
                    group_id=group_id,
                    preferred=preferred,
                )
            )
        cm.groups.append(
            GroupSpec(
                group_id=group_id,
                constraint_id=c.id,
                source_request_id=c.source_request_id,
                label=c.label,
                is_default=c.is_default,
                strength=c.strength,
                weight=c.weight,
                chunk_keys=keys,
                target_slots=p_total,
                exact_count=exact_count,
            )
        )


def _compile_blackout(cm: CompiledModel, c: Blackout, grid: TimeGrid) -> None:
    first = 0 if c.date_from is None else max(0, grid.day_of_date(c.date_from))
    last = grid.days - 1 if c.date_to is None else min(grid.days - 1, grid.day_of_date(c.date_to))
    days = range(first, last + 1)
    if c.weekdays:
        allowed = {WEEKDAY_INDEX[wd] for wd in c.weekdays}
        days = [d for d in days if grid.date_of_day(d).weekday() in allowed]
    ranges = merge_ranges([r for d in days for r in _day_windows(c.windows, d, grid)])
    if not ranges:
        return
    cm.blackouts.append(
        BlackoutSpec(
            constraint_id=c.id,
            source_request_id=c.source_request_id,
            label=c.label,
            is_default=c.is_default,
            strength=c.strength,
            weight=c.weight,
            ranges=ranges,
            categories=frozenset(c.applies_to) if c.applies_to else None,
        )
    )


def compile_constraints(constraints: list[AnyConstraint], grid: TimeGrid, max_chunks: int = 2000) -> CompiledModel:
    cm = CompiledModel(n_slots=grid.n_slots)
    active = [c for c in constraints if c.active]

    buffer_slots = 0
    for c in active:
        if isinstance(c, BufferRule):
            buffer_slots = max(buffer_slots, minutes_to_slots(c.minutes))
            _note_request(cm, c)

    for c in active:
        if isinstance(c, FixedEvent):
            _note_request(cm, c)
            _compile_fixed_event(cm, c, grid, buffer_slots)
        elif isinstance(c, FlexibleTask):
            _note_request(cm, c)
            _compile_flexible_task(cm, c, grid, buffer_slots)
        elif isinstance(c, RecurringBudget):
            _note_request(cm, c)
            _compile_budget(cm, c, grid)
        elif isinstance(c, Blackout):
            _note_request(cm, c)
            _compile_blackout(cm, c, grid)
        elif isinstance(c, MaxStretch):
            _note_request(cm, c)
            cm.stretches.append(
                MaxStretchSpec(
                    constraint_id=c.id,
                    source_request_id=c.source_request_id,
                    label=c.label,
                    is_default=c.is_default,
                    strength=c.strength,
                    weight=c.weight,
                    category=c.category,
                    max_slots=minutes_to_slots(c.max_minutes),
                    gap_slots=minutes_to_slots(c.min_gap_minutes),
                )
            )

    if len(cm.chunks) > max_chunks:
        raise ModelTooLargeError(
            f"Le planning contient trop de blocs à placer ({len(cm.chunks)} > {max_chunks}). "
            "Réduisez le nombre de tâches fractionnées ou de budgets récurrents."
        )
    return cm
