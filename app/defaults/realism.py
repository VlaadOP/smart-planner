"""Contraintes de réalisme injectées par défaut à la création de session.

Toutes SOFT avec des poids étagés, marquées is_default=True et rattachées à un
source_request_id "default:<nom>" : l'utilisateur peut les surcharger d'une
simple phrase ("je travaille de nuit") — le parseur émet alors MODIFY/DELETE
sur leur id, visible dans la table de contraintes du prompt marquée [DEFAULT].
"""
from __future__ import annotations

from app.schemas.ir import (
    ActivityCategory,
    AnyConstraint,
    Blackout,
    MaxStretch,
    RecurringBudget,
    Strength,
    TimeWindow,
)


def default_constraints() -> list[AnyConstraint]:
    return [
        RecurringBudget(
            id="def-sleep",
            source_request_id="default:sleep",
            is_default=True,
            strength=Strength.SOFT,
            weight=80,
            label="Sommeil (8h/nuit)",
            category=ActivityCategory.SLEEP,
            period="DAY",
            total_minutes=480,
            occurrences=1,
            min_chunk_minutes=480,
            required_window=TimeWindow(start="21:00", end="10:00"),
            preferred_window=TimeWindow(start="23:00", end="07:00"),
        ),
        RecurringBudget(
            id="def-breakfast",
            source_request_id="default:meals",
            is_default=True,
            strength=Strength.SOFT,
            weight=40,
            label="Petit-déjeuner",
            category=ActivityCategory.MEAL,
            period="DAY",
            total_minutes=30,
            occurrences=1,
            chunk_minutes=30,
            required_window=TimeWindow(start="06:00", end="10:30"),
        ),
        RecurringBudget(
            id="def-lunch",
            source_request_id="default:meals",
            is_default=True,
            strength=Strength.SOFT,
            weight=40,
            label="Déjeuner",
            category=ActivityCategory.MEAL,
            period="DAY",
            total_minutes=45,
            occurrences=1,
            chunk_minutes=45,
            required_window=TimeWindow(start="11:30", end="14:30"),
        ),
        RecurringBudget(
            id="def-dinner",
            source_request_id="default:meals",
            is_default=True,
            strength=Strength.SOFT,
            weight=40,
            label="Dîner",
            category=ActivityCategory.MEAL,
            period="DAY",
            total_minutes=45,
            occurrences=1,
            chunk_minutes=45,
            required_window=TimeWindow(start="18:30", end="21:30"),
        ),
        Blackout(
            id="def-night",
            source_request_id="default:no-night-work",
            is_default=True,
            strength=Strength.SOFT,
            weight=60,
            label="Pas d'activité en pleine nuit",
            windows=[TimeWindow(start="00:00", end="07:00")],
            # Sport/perso inclus : par défaut on ne place pas une séance à 3h du
            # matin. Sommeil et repas gardent évidemment le droit d'y être.
            applies_to=[
                ActivityCategory.WORK,
                ActivityCategory.MEETING,
                ActivityCategory.SPORT,
                ActivityCategory.PERSONAL,
            ],
        ),
        MaxStretch(
            id="def-stretch",
            source_request_id="default:max-work-stretch",
            is_default=True,
            strength=Strength.SOFT,
            weight=50,
            label="Max 4h de travail d'affilée",
            category=ActivityCategory.WORK,
            max_minutes=240,
            min_gap_minutes=15,
        ),
        Blackout(
            id="def-weekend",
            source_request_id="default:weekend-rest",
            is_default=True,
            strength=Strength.SOFT,
            weight=20,
            label="Repos le week-end",
            weekdays=["SAT", "SUN"],
            applies_to=[ActivityCategory.WORK],
        ),
    ]
