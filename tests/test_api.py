"""Tests API bout-en-bout avec parseur/explainer mockés (aucun appel Gemini)."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.schemas.actions import (
    ConstraintAction,
    ConstraintEnvelope,
    InfeasibilityReport,
    ParseResult,
    RelaxationProposal,
)
from app.schemas.ir import FixedEventFields, Recurrence

TODAY = date.today()
D3 = (TODAY + timedelta(days=3)).isoformat()


def fixed_event_envelope(label: str, start_time: str = "14:00", on: str = D3) -> ConstraintEnvelope:
    return ConstraintEnvelope(
        kind="FIXED_EVENT",
        fixed_event=FixedEventFields(
            label=label,
            recurrence=Recurrence(freq="ONCE", on_date=date.fromisoformat(on)),
            start_time=start_time,
            duration_minutes=60,
        ),
    )


class StubParser:
    """File de ParseResult à renvoyer, dans l'ordre."""

    def __init__(self):
        self.queue: list[ParseResult] = []

    def __call__(self, state, message) -> ParseResult:
        return self.queue.pop(0)


@pytest.fixture
def client_and_stub(tmp_path):
    cfg = Settings(_env_file=None, sessions_dir=tmp_path, solver_workers=1)
    app = create_app(cfg)
    stub = StubParser()
    app.state.parse_fn = stub
    app.state.explain_fn = None  # repli déterministe (services.fallback_explanation)
    return TestClient(app), stub, app


def create_session(client) -> dict:
    res = client.post("/api/sessions", json={})
    assert res.status_code == 200
    return res.json()


def test_create_session_solves_defaults(client_and_stub):
    client, _, _ = client_and_stub
    view = create_session(client)
    assert view["solver_status"] in ("OPTIMAL", "FEASIBLE")
    assert len(view["schedule"]["blocks"]) > 50  # sommeil + repas sur 30 jours
    assert any(c["is_default"] for c in view["constraints"])


def test_chat_adds_meeting(client_and_stub):
    client, stub, _ = client_and_stub
    view = create_session(client)
    stub.queue.append(
        ParseResult(
            language="fr",
            actions=[ConstraintAction(action="ADD", constraint=fixed_event_envelope("Réunion test"))],
            assistant_message="Réunion ajoutée.",
        )
    )
    res = client.post(f"/api/sessions/{view['session_id']}/chat", json={"message": "réunion dans 3 jours à 14h"})
    assert res.status_code == 200
    data = res.json()
    assert data["solver_status"] in ("OPTIMAL", "FEASIBLE")
    meetings = [b for b in data["schedule"]["blocks"] if b["label"] == "Réunion test"]
    assert len(meetings) == 1
    assert meetings[0]["start"].endswith("14:00:00+09:00")
    assert meetings[0]["key"] in data["diff"]["added"]


def test_chat_clarification_skips_solve(client_and_stub):
    client, stub, _ = client_and_stub
    view = create_session(client)
    stub.queue.append(
        ParseResult(
            language="fr",
            actions=[ConstraintAction(action="CLARIFY", clarification_question="Combien de temps ?")],
            assistant_message="Précision nécessaire.",
        )
    )
    res = client.post(f"/api/sessions/{view['session_id']}/chat", json={"message": "du sport"})
    assert res.json()["assistant_message"] == "Combien de temps ?"


def test_conflict_then_relaxation(client_and_stub):
    client, stub, app = client_and_stub
    view = create_session(client)
    sid = view["session_id"]

    # Deux événements durs au même créneau -> INFEASIBLE
    stub.queue.append(
        ParseResult(
            language="fr",
            actions=[
                ConstraintAction(action="ADD", constraint=fixed_event_envelope("RDV A")),
                ConstraintAction(action="ADD", constraint=fixed_event_envelope("RDV B")),
            ],
            assistant_message="Deux rendez-vous ajoutés.",
        )
    )
    res = client.post(f"/api/sessions/{sid}/chat", json={"message": "deux rdv en même temps"})
    data = res.json()
    assert data["solver_status"] == "INFEASIBLE"
    assert data["infeasibility"] is not None
    assert data["infeasibility"]["conflicting_request_ids"] == ["req-001"]
    # Le dernier planning faisable est conservé (jamais de crash)
    assert len(data["schedule"]["blocks"]) > 50

    # Export refusé tant que le conflit persiste
    assert client.post(f"/api/sessions/{sid}/export").status_code == 409

    # On injecte un explainer stub avec une proposition applicable (DELETE RDV B)
    state = app.state.store.get(sid)
    rdv_b = next(c for c in state.constraints if c.label == "RDV B")
    state.last_infeasibility = InfeasibilityReport(
        explanation="Conflit RDV A / RDV B.",
        conflicting_request_ids=["req-001"],
        proposals=[
            RelaxationProposal(
                description="Supprimer RDV B",
                patch=[ConstraintAction(action="DELETE", target_constraint_id=rdv_b.id)],
            )
        ],
    )

    res = client.post(f"/api/sessions/{sid}/relaxations/0/accept")
    assert res.status_code == 200
    data = res.json()
    assert data["solver_status"] in ("OPTIMAL", "FEASIBLE")
    labels = [b["label"] for b in data["schedule"]["blocks"]]
    assert "RDV A" in labels and "RDV B" not in labels


def test_delete_constraint_and_export(client_and_stub):
    client, stub, _ = client_and_stub
    view = create_session(client)
    sid = view["session_id"]
    stub.queue.append(
        ParseResult(
            language="fr",
            actions=[ConstraintAction(action="ADD", constraint=fixed_event_envelope("Rdv dentiste"))],
            assistant_message="Ajouté.",
        )
    )
    client.post(f"/api/sessions/{sid}/chat", json={"message": "dentiste"})

    res = client.post(f"/api/sessions/{sid}/export")
    assert res.status_code == 200
    body = res.content.decode("utf-8", errors="replace")
    assert "BEGIN:VCALENDAR" in body
    assert "Rdv dentiste" in body
    # Les blocs par défaut (sommeil...) ne sont pas exportés par défaut
    assert "Sommeil" not in body

    constraints = client.get(f"/api/sessions/{sid}/constraints").json()
    cid = next(c["id"] for c in constraints if c["label"] == "Rdv dentiste")
    res = client.delete(f"/api/sessions/{sid}/constraints/{cid}")
    assert res.status_code == 200
    labels = [b["label"] for b in res.json()["schedule"]["blocks"]]
    assert "Rdv dentiste" not in labels


def test_session_persistence(client_and_stub, tmp_path):
    client, _, app = client_and_stub
    view = create_session(client)
    sid = view["session_id"]
    # purge du cache mémoire -> relecture depuis le disque
    app.state.store._cache.clear()
    res = client.get(f"/api/sessions/{sid}")
    assert res.status_code == 200
    assert res.json()["session_id"] == sid
    assert len(res.json()["schedule"]["blocks"]) > 50
