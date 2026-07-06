"""Configuration globale (pydantic-settings, .env)."""
from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(BASE_DIR / ".env"), extra="ignore")

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    timezone: str = "Asia/Tokyo"
    horizon_days: int = 30

    solver_time_limit_s: float = 10.0
    solver_core_time_limit_s: float = 3.0
    solver_workers: int = 8
    solver_seed: int = 42
    # Garde-fou : au-delà, on refuse de construire le modèle (message convivial).
    max_chunks: int = 2000

    # Paliers de l'objectif (voir solver/model.py)
    tier_user_soft: int = 100
    tier_default_soft: int = 10
    stability_weight: int = 20
    pref_window_weight: int = 1
    # Pénalité par paire d'occurrences d'un même budget hebdomadaire placées à
    # moins de 24 h l'une de l'autre : pousse à étaler (ex. sport) sur la semaine.
    spread_penalty: int = 300

    sessions_dir: Path = BASE_DIR / "sessions"

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


settings = Settings()
