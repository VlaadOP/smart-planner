"""Grille temporelle : conversions wall-clock <-> slots de 15 min sur l'horizon.

Axe linéaire : slot = jour_index * 96 + offset_intra_jour. Chaque jour compte
exactement 96 slots (pas de gestion DST — Asia/Tokyo par défaut n'en a pas ;
pour une tz à DST, les jours de changement seraient décalés d'une heure au
pire, ce qui est acceptable pour un planificateur personnel).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.schemas.ir import WEEKDAY_INDEX, Recurrence, TimeWindow, Weekday

SLOT_MINUTES = 15
SLOTS_PER_DAY = 96


def hhmm_to_offset(hhmm: str) -> int:
    """"14:30" -> nombre de slots depuis minuit (58)."""
    h, m = hhmm.split(":")
    return int(h) * 4 + int(m) // SLOT_MINUTES


def minutes_to_slots(minutes: int) -> int:
    if minutes % SLOT_MINUTES != 0:
        raise ValueError(f"{minutes} minutes is not a multiple of {SLOT_MINUTES}")
    return minutes // SLOT_MINUTES


class TimeGrid:
    def __init__(self, horizon_start: date, horizon_days: int, tz: ZoneInfo):
        self.start_date = horizon_start
        self.days = horizon_days
        self.tz = tz
        self.n_slots = horizon_days * SLOTS_PER_DAY

    @property
    def end_date(self) -> date:
        return self.start_date + timedelta(days=self.days - 1)

    def date_of_day(self, day: int) -> date:
        return self.start_date + timedelta(days=day)

    def day_of_date(self, d: date) -> int:
        return (d - self.start_date).days

    def weekday_of_day(self, day: int) -> Weekday:
        return list(Weekday)[self.date_of_day(day).weekday()]

    def slot_to_datetime(self, slot: int) -> datetime:
        day, rem = divmod(slot, SLOTS_PER_DAY)
        d = self.date_of_day(day)
        return datetime.combine(d, time(hour=rem // 4, minute=(rem % 4) * SLOT_MINUTES), tzinfo=self.tz)

    def datetime_to_slot(self, dt: datetime) -> int:
        local = dt.astimezone(self.tz)
        day = self.day_of_date(local.date())
        return day * SLOTS_PER_DAY + local.hour * 4 + local.minute // SLOT_MINUTES

    def recurrence_days(self, rec: Recurrence) -> list[int]:
        """Indices de jours (0-based dans l'horizon) où la récurrence s'applique."""
        last = self.days - 1
        if rec.until is not None:
            last = min(last, self.day_of_date(rec.until))
        if rec.freq == "ONCE":
            assert rec.on_date is not None
            day = self.day_of_date(rec.on_date)
            return [day] if 0 <= day <= last else []
        days = range(0, last + 1)
        if rec.weekdays:  # WEEKLY avec jours donnés ; toléré aussi sur DAILY
            allowed = {WEEKDAY_INDEX[wd] for wd in rec.weekdays}
            return [d for d in days if self.date_of_day(d).weekday() in allowed]
        return list(days)

    def window_slot_range(self, day: int, w: TimeWindow) -> tuple[int, int] | None:
        """Fenêtre [start, end) en slots sur l'axe linéaire pour la fenêtre ancrée au jour `day`.
        Une fenêtre qui passe minuit (end <= start) déborde sur le jour suivant ;
        end == start == "00:00" etc. signifie 24 h. Clippée à l'horizon ; None si vide."""
        s_off = hhmm_to_offset(w.start)
        e_off = hhmm_to_offset(w.end)
        start = day * SLOTS_PER_DAY + s_off
        if e_off > s_off:
            end = day * SLOTS_PER_DAY + e_off
        else:
            end = (day + 1) * SLOTS_PER_DAY + e_off
        start = max(0, start)
        end = min(self.n_slots, end)
        return (start, end) if start < end else None

    def day_range(self, day: int) -> tuple[int, int]:
        return (day * SLOTS_PER_DAY, (day + 1) * SLOTS_PER_DAY)


def merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Fusionne des intervalles [a, b) qui se chevauchent ou sont adjacents."""
    if not ranges:
        return []
    ranges = sorted(ranges)
    out = [ranges[0]]
    for a, b in ranges[1:]:
        la, lb = out[-1]
        if a <= lb:
            out[-1] = (la, max(lb, b))
        else:
            out.append((a, b))
    return out
