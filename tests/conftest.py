from datetime import date

import pytest

from app.compiler.timegrid import TimeGrid
from app.config import Settings

# Un lundi ; horizon de 30 jours => jours 0..29, mardis = jours 1, 8, 15, 22, 29.
HORIZON_START = date(2026, 7, 6)


@pytest.fixture
def cfg() -> Settings:
    # 1 worker + seed fixe = solves déterministes (reproductibilité des tests)
    return Settings(_env_file=None, solver_workers=1, solver_time_limit_s=15.0)


@pytest.fixture
def grid(cfg) -> TimeGrid:
    return TimeGrid(HORIZON_START, cfg.horizon_days, cfg.tz)
