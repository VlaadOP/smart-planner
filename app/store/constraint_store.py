"""Application des actions du parseur au store de contraintes (merge)."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas.actions import ActionType, ConstraintAction
from app.store.session import SessionState


@dataclass
class MergeResult:
    applied: int = 0
    clarification: str | None = None
    errors: list[str] = field(default_factory=list)


def apply_actions(state: SessionState, actions: list[ConstraintAction], source_request_id: str) -> MergeResult:
    """ADD : estampille et ajoute. MODIFY : remplace le payload en gardant l'id
    (et is_default). DELETE : désactivation douce. CLARIFY : court-circuite."""
    result = MergeResult()
    by_id = {c.id: i for i, c in enumerate(state.constraints)}

    for action in actions:
        if action.action == ActionType.CLARIFY:
            result.clarification = action.clarification_question
            continue

        if action.action == ActionType.ADD:
            state.constraints.append(action.constraint.to_constraint(source_request_id))
            result.applied += 1
            by_id = {c.id: i for i, c in enumerate(state.constraints)}
            continue

        idx = by_id.get(action.target_constraint_id or "")
        if idx is None:
            result.errors.append(
                f"Constraint not found: {action.target_constraint_id!r} (action {action.action.value})"
            )
            continue
        old = state.constraints[idx]

        if action.action == ActionType.DELETE:
            old.active = False
            result.applied += 1
        elif action.action == ActionType.MODIFY:
            replacement = action.constraint.to_constraint(
                source_request_id, constraint_id=old.id, is_default=old.is_default
            )
            state.constraints[idx] = replacement
            result.applied += 1
    return result
