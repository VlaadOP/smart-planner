"""Validation de la frontière Gemini : enveloppe plate + cohérence des actions."""
import pytest
from pydantic import ValidationError

from app.schemas.actions import ConstraintAction, ConstraintEnvelope
from app.schemas.ir import FixedEvent, FixedEventFields, Recurrence, RecurringBudgetFields


def make_fixed_event_fields() -> dict:
    return FixedEventFields(
        label="Réunion",
        recurrence=Recurrence(freq="DAILY"),
        start_time="14:00",
        duration_minutes=60,
    ).model_dump()


def test_envelope_requires_matching_payload():
    with pytest.raises(ValidationError):
        ConstraintEnvelope(kind="FIXED_EVENT")  # aucun payload
    with pytest.raises(ValidationError):
        ConstraintEnvelope(
            kind="FIXED_EVENT",
            recurring_budget=RecurringBudgetFields(
                label="x", category="break", period="DAY", total_minutes=60
            ),
        )  # payload du mauvais type


def test_envelope_to_constraint_stamps_server_fields():
    env = ConstraintEnvelope(kind="FIXED_EVENT", fixed_event=make_fixed_event_fields())
    c = env.to_constraint(source_request_id="req42")
    assert isinstance(c, FixedEvent)
    assert c.source_request_id == "req42"
    assert not c.is_default and c.active and c.id


def test_action_coherence():
    env = ConstraintEnvelope(kind="FIXED_EVENT", fixed_event=make_fixed_event_fields())
    with pytest.raises(ValidationError):
        ConstraintAction(action="ADD")  # ADD sans contrainte
    with pytest.raises(ValidationError):
        ConstraintAction(action="MODIFY", constraint=env)  # MODIFY sans cible
    with pytest.raises(ValidationError):
        ConstraintAction(action="DELETE")  # DELETE sans cible
    with pytest.raises(ValidationError):
        ConstraintAction(action="CLARIFY")  # CLARIFY sans question
    ConstraintAction(action="DELETE", target_constraint_id="abc")  # ok


def test_hhmm_alignment_rejected():
    fields = make_fixed_event_fields()
    fields["start_time"] = "14:10"  # pas aligné sur 15 min
    with pytest.raises(ValidationError):
        ConstraintEnvelope(kind="FIXED_EVENT", fixed_event=fields)
