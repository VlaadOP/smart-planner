"""Frontière Gemini : enveloppe plate (pas d'anyOf) + actions ADD/MODIFY/DELETE/CLARIFY.

Le schéma passé à Gemini est dérivé de ces modèles. Les unions discriminées ne
traversent JAMAIS cette frontière : l'enveloppe expose un champ optionnel par type
de contrainte et un ``kind`` qui dit lequel est renseigné. La validation Pydantic
(re-parse côté serveur) garantit la cohérence et alimente la boucle de réparation.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from app.schemas.ir import (
    AnyConstraint,
    Blackout,
    BlackoutFields,
    BufferRule,
    BufferRuleFields,
    FixedEvent,
    FixedEventFields,
    FlexibleTask,
    FlexibleTaskFields,
    MaxStretch,
    MaxStretchFields,
    RecurringBudget,
    RecurringBudgetFields,
)


class ConstraintKind(str, Enum):
    FIXED_EVENT = "FIXED_EVENT"
    FLEXIBLE_TASK = "FLEXIBLE_TASK"
    RECURRING_BUDGET = "RECURRING_BUDGET"
    BLACKOUT = "BLACKOUT"
    BUFFER_RULE = "BUFFER_RULE"
    MAX_STRETCH = "MAX_STRETCH"


# kind -> (nom du champ payload, classe IR complète)
KIND_MAP: dict[ConstraintKind, tuple[str, type]] = {
    ConstraintKind.FIXED_EVENT: ("fixed_event", FixedEvent),
    ConstraintKind.FLEXIBLE_TASK: ("flexible_task", FlexibleTask),
    ConstraintKind.RECURRING_BUDGET: ("recurring_budget", RecurringBudget),
    ConstraintKind.BLACKOUT: ("blackout", Blackout),
    ConstraintKind.BUFFER_RULE: ("buffer_rule", BufferRule),
    ConstraintKind.MAX_STRETCH: ("max_stretch", MaxStretch),
}


class ConstraintEnvelope(BaseModel):
    """Exactement un payload renseigné, correspondant à ``kind`` (Gemini-safe)."""

    kind: ConstraintKind
    fixed_event: Optional[FixedEventFields] = None
    flexible_task: Optional[FlexibleTaskFields] = None
    recurring_budget: Optional[RecurringBudgetFields] = None
    blackout: Optional[BlackoutFields] = None
    buffer_rule: Optional[BufferRuleFields] = None
    max_stretch: Optional[MaxStretchFields] = None

    @model_validator(mode="after")
    def _exactly_one_payload(self) -> "ConstraintEnvelope":
        field_name, _ = KIND_MAP[self.kind]
        filled = [name for name, _cls in KIND_MAP.values() if getattr(self, name) is not None]
        if filled != [field_name]:
            raise ValueError(
                f"kind={self.kind.value} requires exactly the payload field "
                f"'{field_name}' to be set (got: {filled or 'none'})"
            )
        return self

    def to_constraint(
        self, source_request_id: str, *, constraint_id: str | None = None, is_default: bool = False
    ) -> AnyConstraint:
        """Estampille les champs serveur et produit la contrainte IR interne."""
        field_name, cls = KIND_MAP[self.kind]
        payload: BaseModel = getattr(self, field_name)
        kwargs = payload.model_dump()
        kwargs["source_request_id"] = source_request_id
        kwargs["is_default"] = is_default
        if constraint_id is not None:
            kwargs["id"] = constraint_id
        return cls(**kwargs)


class ActionType(str, Enum):
    ADD = "ADD"
    MODIFY = "MODIFY"
    DELETE = "DELETE"
    CLARIFY = "CLARIFY"


class ConstraintAction(BaseModel):
    action: ActionType
    target_constraint_id: Optional[str] = None  # MODIFY/DELETE : id réel issu du contexte
    constraint: Optional[ConstraintEnvelope] = None  # ADD/MODIFY : payload complet (remplacement)
    clarification_question: Optional[str] = None  # CLARIFY

    @model_validator(mode="after")
    def _coherent(self) -> "ConstraintAction":
        a = self.action
        if a == ActionType.ADD and self.constraint is None:
            raise ValueError("ADD requires 'constraint'")
        if a == ActionType.MODIFY and (self.constraint is None or not self.target_constraint_id):
            raise ValueError("MODIFY requires 'target_constraint_id' and 'constraint'")
        if a == ActionType.DELETE and not self.target_constraint_id:
            raise ValueError("DELETE requires 'target_constraint_id'")
        if a == ActionType.CLARIFY and not self.clarification_question:
            raise ValueError("CLARIFY requires 'clarification_question'")
        return self


class ParseResult(BaseModel):
    """Sortie structurée du parseur Gemini pour un message utilisateur."""

    language: str = Field(default="fr", pattern="^(fr|en)$")
    actions: list[ConstraintAction] = Field(default_factory=list)
    assistant_message: str  # courte confirmation affichée dans le chat, dans la langue de l'utilisateur


class RelaxationProposal(BaseModel):
    description: str  # langage naturel, langue de l'utilisateur
    patch: list[ConstraintAction] = Field(default_factory=list)  # applicable machine


class InfeasibilityReport(BaseModel):
    explanation: str
    conflicting_request_ids: list[str] = Field(default_factory=list)
    proposals: list[RelaxationProposal] = Field(default_factory=list)
