"""IR de contraintes — le pont exact entre la sortie du LLM et l'entrée du solveur CP-SAT.

Convention temps : l'IR est exprimé en heure humaine (dates ISO, "HH:MM" alignés sur
15 minutes). La conversion en indices de slots est faite par app/compiler, jamais ici.

Les classes ``*Fields`` portent les champs que le LLM a le droit de produire ; les
classes finales (FixedEvent, ...) y ajoutent les champs estampillés côté serveur
(id, source_request_id, is_default, active) et un discriminant ``type`` interne.
"""
from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Annotated, Literal, Optional, Union
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


def new_id() -> str:
    return uuid4().hex[:12]


class Weekday(str, Enum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"
    SUN = "SUN"


WEEKDAY_INDEX: dict[Weekday, int] = {wd: i for i, wd in enumerate(Weekday)}  # MON=0 .. SUN=6


class Strength(str, Enum):
    HARD = "hard"  # violation => infaisable (littéral d'assomption attaché à la requête)
    SOFT = "soft"  # violation pénalisée par weight


class ActivityCategory(str, Enum):
    WORK = "work"
    SLEEP = "sleep"
    MEAL = "meal"
    BREAK = "break"
    SPORT = "sport"
    PERSONAL = "personal"
    MEETING = "meeting"
    OTHER = "other"


# Le LLM doit émettre des heures alignées sur 15 min ; sinon la validation échoue
# bruyamment et déclenche la boucle de réparation.
HHMM = Annotated[str, Field(pattern=r"^([01]\d|2[0-3]):(00|15|30|45)$")]


class TimeWindow(BaseModel):
    """Fenêtre horaire intra-journée. Si end <= start, la fenêtre passe minuit
    (ex. 22:00 -> 09:00) ; end == start signifie 24 h."""

    start: HHMM
    end: HHMM


class Recurrence(BaseModel):
    """Sous-ensemble pragmatique de RRULE : ONCE / DAILY / WEEKLY."""

    freq: Literal["ONCE", "DAILY", "WEEKLY"]
    on_date: Optional[date] = None  # requis si ONCE
    weekdays: list[Weekday] = Field(default_factory=list)  # WEEKLY ; vide = tous les jours
    until: Optional[date] = None  # défaut = fin d'horizon

    @model_validator(mode="after")
    def _check(self) -> "Recurrence":
        if self.freq == "ONCE" and self.on_date is None:
            raise ValueError("recurrence ONCE requires on_date")
        return self


# ---------------------------------------------------------------------------
# Champs produits par le LLM (payloads de l'enveloppe Gemini)
# ---------------------------------------------------------------------------

class _CommonFields(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    strength: Strength = Strength.HARD
    weight: int = Field(default=50, ge=1, le=100)  # significatif seulement si SOFT


class FixedEventFields(_CommonFields):
    """Événement épinglé : 'réunion fixe mardi à 14h'."""

    category: ActivityCategory = ActivityCategory.MEETING
    recurrence: Recurrence
    start_time: HHMM
    duration_minutes: int = Field(ge=15, le=1440, multiple_of=15)
    location: Optional[str] = None


class FlexibleTaskFields(_CommonFields):
    """Tâche placée par le solveur : 'finir le rapport (3h) avant vendredi'."""

    category: ActivityCategory = ActivityCategory.WORK
    duration_minutes: int = Field(ge=15, le=2880, multiple_of=15)
    earliest: Optional[date] = None
    deadline: Optional[date] = None  # la tâche doit se terminer au plus tard ce jour-là
    allowed_windows: list[TimeWindow] = Field(default_factory=list)  # vide = toute heure
    allowed_weekdays: list[Weekday] = Field(default_factory=list)  # vide = tous
    splittable: bool = False
    min_chunk_minutes: int = Field(default=30, ge=15, multiple_of=15)
    max_chunk_minutes: Optional[int] = Field(default=None, ge=15, multiple_of=15)
    location: Optional[str] = None


class RecurringBudgetFields(_CommonFields):
    """Quantité par période : '1h de pause par jour', '10h de sommeil',
    '3x45min de sport par semaine'."""

    category: ActivityCategory
    period: Literal["DAY", "WEEK"]
    total_minutes: int = Field(ge=15, le=1440 * 7, multiple_of=15)
    occurrences: Optional[int] = Field(default=None, ge=1, le=16)  # ex. 3 pour "3x/semaine"
    chunk_minutes: Optional[int] = Field(default=None, ge=15, multiple_of=15)  # taille fixe d'occurrence
    min_chunk_minutes: int = Field(default=15, ge=15, multiple_of=15)
    weekdays: list[Weekday] = Field(default_factory=list)  # vide = tous les jours (période DAY)
    preferred_window: Optional[TimeWindow] = None  # indication de placement (soft)
    required_window: Optional[TimeWindow] = None  # placement obligatoire (ex. sommeil 22:00-09:00)


class BlackoutFields(_CommonFields):
    """Fenêtres interdites : 'jamais avant 9h', 'pas de travail le week-end'."""

    windows: list[TimeWindow] = Field(default_factory=list)  # vide = journée entière
    weekdays: list[Weekday] = Field(default_factory=list)  # vide = tous les jours
    applies_to: list[ActivityCategory] = Field(default_factory=list)  # vide = toute activité
    date_from: Optional[date] = None
    date_to: Optional[date] = None


class BufferRuleFields(_CommonFields):
    """Tampon de transition/trajet autour des événements localisés."""

    minutes: int = Field(ge=15, le=240, multiple_of=15)
    between_different_locations_only: bool = True


class MaxStretchFields(_CommonFields):
    """Durée continue maximale d'une catégorie : 'max 4h de travail d'affilée'."""

    category: ActivityCategory
    max_minutes: int = Field(ge=30, le=1440, multiple_of=15)
    min_gap_minutes: int = Field(default=15, ge=15, multiple_of=15)


# ---------------------------------------------------------------------------
# Contraintes complètes (IR interne = payload LLM + champs serveur)
# ---------------------------------------------------------------------------

class ServerFields(BaseModel):
    id: str = Field(default_factory=new_id)
    source_request_id: str  # lien vers la requête utilisateur d'origine (cœur unsat)
    is_default: bool = False  # contrainte de réalisme injectée, pas écrite par l'utilisateur
    active: bool = True  # suppression douce


class FixedEvent(ServerFields, FixedEventFields):
    type: Literal["fixed_event"] = "fixed_event"


class FlexibleTask(ServerFields, FlexibleTaskFields):
    type: Literal["flexible_task"] = "flexible_task"


class RecurringBudget(ServerFields, RecurringBudgetFields):
    type: Literal["recurring_budget"] = "recurring_budget"


class Blackout(ServerFields, BlackoutFields):
    type: Literal["blackout"] = "blackout"


class BufferRule(ServerFields, BufferRuleFields):
    type: Literal["buffer_rule"] = "buffer_rule"


class MaxStretch(ServerFields, MaxStretchFields):
    type: Literal["max_stretch"] = "max_stretch"


AnyConstraint = Annotated[
    Union[FixedEvent, FlexibleTask, RecurringBudget, Blackout, BufferRule, MaxStretch],
    Field(discriminator="type"),
]


class ConstraintList(BaseModel):
    """Wrapper de (dé)sérialisation pour la persistance JSON du store."""

    constraints: list[AnyConstraint] = Field(default_factory=list)
