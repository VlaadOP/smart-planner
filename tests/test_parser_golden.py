"""Golden tests offline : les sorties Gemini enregistrées doivent (1) valider le
schéma ParseResult, (2) se convertir en contraintes IR, (3) se compiler.

Ces fixtures épinglent le contrat LLM<->serveur ; le smoke test live
(test_gemini_live.py) vérifie que le vrai modèle le respecte toujours."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.compiler.compile import compile_constraints
from app.schemas.actions import ActionType, ParseResult

GOLDEN_DIR = Path(__file__).parent / "golden" / "gemini_parse"
GOLDEN_FILES = sorted(GOLDEN_DIR.glob("*.json"))


@pytest.mark.parametrize("path", GOLDEN_FILES, ids=lambda p: p.stem)
def test_golden_parse(path: Path, grid):
    data = json.loads(path.read_text(encoding="utf-8"))
    result = ParseResult.model_validate(data["parse_result"])
    assert result.assistant_message
    assert result.actions

    added = []
    for action in result.actions:
        if action.action in (ActionType.ADD, ActionType.MODIFY):
            constraint = action.constraint.to_constraint(source_request_id="golden")
            if action.action == ActionType.ADD:
                added.append(constraint)
        elif action.action == ActionType.DELETE:
            assert action.target_constraint_id
        elif action.action == ActionType.CLARIFY:
            assert action.clarification_question

    if added:
        cm = compile_constraints(added, grid)
        assert cm.chunks or cm.blackouts or cm.stretches


def test_golden_dir_not_empty():
    assert len(GOLDEN_FILES) >= 8
