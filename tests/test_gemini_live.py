"""Smoke test live (exclu par défaut ; lancer avec `pytest -m live`).
Vérifie que le vrai modèle Gemini respecte toujours le contrat structuré."""
from datetime import date

import pytest

from app.config import Settings
from app.compiler.timegrid import TimeGrid
from app.llm.client import GeminiClient
from app.llm.parser import parse_message
from app.schemas.actions import ActionType, ConstraintKind


@pytest.mark.live
def test_live_parse_fixed_event():
    cfg = Settings()
    if not cfg.gemini_api_key:
        pytest.skip("GEMINI_API_KEY absente")
    grid = TimeGrid(date(2026, 7, 6), cfg.horizon_days, cfg.tz)
    client = GeminiClient(cfg)
    result = parse_message(
        client,
        "Réunion fixe tous les mardis à 14h pendant une heure",
        constraints=[],
        history=[],
        grid=grid,
        today=date(2026, 7, 6),
    )
    assert result.language == "fr"
    adds = [a for a in result.actions if a.action == ActionType.ADD]
    assert len(adds) == 1
    assert adds[0].constraint.kind == ConstraintKind.FIXED_EVENT
    fe = adds[0].constraint.fixed_event
    assert fe.start_time == "14:00"
    assert fe.duration_minutes == 60
