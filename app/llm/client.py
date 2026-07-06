"""Client Gemini : appel structuré + boucle de réparation.

Le schéma de sortie est dérivé des modèles Pydantic (le SDK google-genai
accepte directement une classe Pydantic comme response_schema). La sortie
brute est TOUJOURS re-validée par Pydantic côté serveur ; en cas d'échec, un
unique retry renvoie l'erreur exacte au modèle pour correction.
"""
from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.config import Settings

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Le LLM n'a pas produit de sortie valide après réparation."""


class GeminiClient:
    def __init__(self, cfg: Settings):
        if not cfg.gemini_api_key:
            raise LLMError(
                "GEMINI_API_KEY manquante : ajoutez-la dans le fichier .env à la racine du projet."
            )
        # Import paresseux : le reste de l'app (solveur, tests) ne dépend pas du SDK.
        from google import genai

        self._genai = genai
        self._client = genai.Client(api_key=cfg.gemini_api_key)
        self._model = cfg.gemini_model

    def structured(self, system: str, user: str, schema: type[T], repair_attempts: int = 1) -> T:
        from google.genai import types

        contents = user
        last_error: Exception | None = None
        for _ in range(repair_attempts + 1):
            response = self._client.models.generate_content(
                model=self._model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    response_schema=schema,
                    temperature=0.2,
                ),
            )
            raw = response.text or ""
            try:
                return schema.model_validate_json(raw)
            except ValidationError as e:
                last_error = e
                contents = (
                    f"{user}\n\n---\nYour previous JSON output failed validation.\n"
                    f"Output was:\n{raw}\n\nValidation errors:\n{e}\n\n"
                    "Emit a corrected JSON object only, matching the schema exactly."
                )
        raise LLMError(f"Sortie Gemini invalide après réparation : {last_error}")
