"""Golden de l'explainer (schéma InfeasibilityReport + patches applicables)."""
import json
from pathlib import Path

from app.schemas.actions import ActionType, InfeasibilityReport

GOLDEN_DIR = Path(__file__).parent / "golden" / "gemini_explain"


def test_explain_golden_valid():
    for path in sorted(GOLDEN_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        report = InfeasibilityReport.model_validate(data["report"])
        assert report.explanation
        assert 2 <= len(report.proposals) <= 3
        for proposal in report.proposals:
            assert proposal.description
            assert proposal.patch
            for action in proposal.patch:
                assert action.action in (ActionType.MODIFY, ActionType.DELETE)
