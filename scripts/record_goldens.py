"""Enregistreur de goldens : appelle le vrai Gemini sur une liste d'énoncés et
sauvegarde les sorties dans tests/golden/gemini_parse/ pour inspection manuelle.

Usage : .venv\\Scripts\\python.exe scripts\\record_goldens.py  (GEMINI_API_KEY requis)
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.compiler.timegrid import TimeGrid
from app.config import settings
from app.defaults.realism import default_constraints
from app.llm.client import GeminiClient
from app.llm.parser import parse_message

UTTERANCES = [
    "Réunion d'équipe tous les mardis à 14h",
    "1h de pause par jour",
    "Je veux dormir 10h par nuit",
    "3 séances de sport de 45 minutes par semaine, de préférence le matin",
    "Jamais de travail avant 9h du matin",
    "J'ai 3h de rapport à finir avant vendredi, je peux le couper en morceaux",
    "Add a dentist appointment on July 15th at 9:30am, 90 minutes",
    "Réserve du temps pour le sport",
]

OUT_DIR = Path(__file__).resolve().parent.parent / "tests" / "golden" / "gemini_parse"


def main() -> None:
    client = GeminiClient(settings)
    today = date.today()
    grid = TimeGrid(today, settings.horizon_days, settings.tz)
    constraints = default_constraints()
    for i, utterance in enumerate(UTTERANCES):
        result = parse_message(client, utterance, constraints, [], grid, today)
        out = OUT_DIR / f"recorded_{i:02d}.json"
        out.write_text(
            json.dumps(
                {"utterance": utterance, "parse_result": result.model_dump(mode="json")},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"[ok] {utterance!r} -> {out.name}")


if __name__ == "__main__":
    main()
