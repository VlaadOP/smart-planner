"""Validateur indépendant du solveur : vérifie un planning contre le
CompiledModel. Utilisé par les tests (« on ne teste pas le solveur avec le
solveur ») et comme garde-fou avant export."""
from __future__ import annotations

from app.compiler.compile import CompiledModel
from app.compiler.timegrid import TimeGrid
from app.schemas.ir import Strength
from app.schemas.schedule import Schedule


def validate_schedule(schedule: Schedule, cm: CompiledModel, grid: TimeGrid) -> list[str]:
    """Retourne la liste des violations HARD (vide = planning valide)."""
    violations: list[str] = []
    slots: dict[str, tuple[int, int]] = {}  # key -> [start, end) hors tampon
    for b in schedule.blocks:
        s = grid.datetime_to_slot(b.start)
        e = grid.datetime_to_slot(b.end)
        slots[b.key] = (s, e)

    # 1. Aucun chevauchement entre blocs (les tampons ne sont pas vérifiés ici)
    ordered = sorted(slots.items(), key=lambda kv: kv[1][0])
    for (k1, (s1, e1)), (k2, (s2, e2)) in zip(ordered, ordered[1:]):
        if s2 < e1:
            violations.append(f"overlap: {k1} [{s1},{e1}) overlaps {k2} [{s2},{e2})")

    chunks_by_key = {c.key: c for c in cm.chunks}

    # 2. Présence et placement des chunks à présence obligatoire (HARD)
    for c in cm.chunks:
        if not (c.required_presence and c.strength == Strength.HARD):
            continue
        if c.key not in slots:
            violations.append(f"missing: {c.label} ({c.key}) absent from schedule")
            continue
        s, e = slots[c.key]
        size = e - s
        if c.fixed_start is not None and s != c.fixed_start:
            violations.append(f"misplaced: {c.label} ({c.key}) at {s}, expected {c.fixed_start}")
        if not (c.min_size <= size <= c.max_size):
            violations.append(f"size: {c.label} ({c.key}) size {size} outside [{c.min_size},{c.max_size}]")
        if c.fixed_start is None and c.windows is not None:
            if not any(s >= a and e <= b for a, b in c.windows):
                violations.append(f"window: {c.label} ({c.key}) [{s},{e}) outside allowed windows")

    # 3. Groupes HARD : somme des tailles et comptes
    for g in cm.groups:
        if g.strength != Strength.HARD:
            continue
        present = [slots[k] for k in g.chunk_keys if k in slots]
        total = sum(e - s for s, e in present)
        if g.target_slots is not None and total != g.target_slots:
            violations.append(f"budget: {g.label} ({g.group_id}) total {total} != {g.target_slots}")
        if g.exact_count is not None and len(present) != g.exact_count:
            violations.append(f"count: {g.label} ({g.group_id}) {len(present)} != {g.exact_count}")

    # 4. Blackouts HARD
    for bo in cm.blackouts:
        if bo.strength != Strength.HARD:
            continue
        for key, (s, e) in slots.items():
            spec = chunks_by_key.get(key)
            if spec is None:
                continue
            if bo.categories is not None and spec.category not in bo.categories:
                continue
            for a, b in bo.ranges:
                if s < b and e > a:
                    violations.append(
                        f"blackout: {spec.label} ({key}) [{s},{e}) in forbidden zone [{a},{b}) of {bo.label}"
                    )

    # 5. MaxStretch HARD
    for st in cm.stretches:
        if st.strength != Strength.HARD:
            continue
        cat_blocks = sorted(
            (v for k, v in slots.items() if (sp := chunks_by_key.get(k)) and sp.category == st.category),
        )
        for s, e in cat_blocks:
            if e - s > st.max_slots:
                violations.append(f"stretch: {st.category.value} block of {e - s} slots > {st.max_slots}")
        for (s1, e1), (s2, e2) in zip(cat_blocks, cat_blocks[1:]):
            if s2 - e1 < st.gap_slots and s2 >= e1:
                violations.append(
                    f"stretch-gap: {st.category.value} blocks separated by {s2 - e1} < {st.gap_slots} slots"
                )
    return violations
