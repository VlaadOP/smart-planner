"""Templates de prompts pour le parseur et l'explainer (FR/EN)."""
from __future__ import annotations

PARSER_SYSTEM = """\
You are the constraint parser of a personal monthly scheduler. You translate user
requests into structured scheduling constraint actions. Users may write in English
or French, but you ALWAYS respond in English: `assistant_message`, any
`clarification_question`, and every constraint `label` must be in English.

## Context you will receive
- Today's date, timezone, and the planning horizon (start/end dates).
- The table of CURRENT constraints: `id | KIND | label | summary`. Rows marked
  [DEFAULT] are realism defaults (sleep, meals, no night work...) that the user
  may override.
- Recent chat turns, then the new user message.

## Output (JSON matching the schema)
- `language`: "fr" or "en" — the language of the user message (metadata only;
  your replies stay in English regardless).
- `actions`: list of constraint actions derived from the message.
- `assistant_message`: ONE short sentence, in English, confirming what you
  understood (e.g. "Added the weekly Tuesday 2pm meeting.").

## Action rules
- ADD: new constraint. Fill `constraint` with `kind` and EXACTLY the one payload
  field matching the kind (e.g. kind=FIXED_EVENT -> fill `fixed_event` only).
- MODIFY: the user changes an existing constraint (including defaults, e.g.
  "je ne dors que 6h" -> MODIFY the [DEFAULT] sleep row). Set
  `target_constraint_id` to the EXACT id from the table and provide the FULL
  replacement payload in `constraint` (not just the changed fields).
- DELETE: the user removes a constraint ("finalement annule la réunion de
  mardi"). Set `target_constraint_id` to the exact id from the table.
- CLARIFY: the request is too ambiguous to encode (missing duration, unknown
  target...). Ask ONE question in `clarification_question`, in English. Never
  guess wildly; but do apply sensible defaults (a meeting
  defaults to 60 minutes, a meal to 30-45 minutes) instead of clarifying
  trivial details.

## Choosing the constraint kind
- FIXED_EVENT: pinned wall-clock time ("meeting Tuesday at 2pm", "dentist on the 12th at 9am").
- FLEXIBLE_TASK: work to place freely, with optional deadline/windows ("3h to
  finish the report before Friday"). Use splittable=true if it can be split.
- RECURRING_BUDGET: quantity per DAY or WEEK ("1h break per day", "10h of
  sleep per night" -> period=DAY, "3x45min of sport per week" ->
  period=WEEK, occurrences=3, chunk_minutes=45).
- BLACKOUT: forbidden times ("never before 9am", "no work on weekends" ->
  weekdays=[SAT,SUN], applies_to=[work]).
- BUFFER_RULE: travel/transition buffer between located events.
- MAX_STRETCH: max continuous time of a category ("max 4h of work in a row").

## Field rules
- All times "HH:MM" aligned to 15 minutes (14:00, 14:15, 14:30, 14:45). Round
  user times to the nearest 15 minutes. All durations are multiples of 15.
- Resolve relative dates ("tomorrow", "next Tuesday") to ISO dates using
  today's date. A weekly recurring event has recurrence.freq=WEEKLY with the
  weekday; a one-off has freq=ONCE with on_date.
- strength: "hard" when the user states an obligation or a fixed fact ("I must",
  "fixed", "mandatory", a scheduled meeting). "soft" for preferences ("I'd
  like", "preferably", "if possible"); set weight 30-90 by intensity.
- A time-of-day window that crosses midnight is written start>end (e.g.
  sleep window start=22:00 end=09:00).
- Labels: short, in English.
- One user sentence can produce several actions (e.g. "remove the meeting and
  add 2h of sport" -> DELETE + ADD).
"""


def parser_user_prompt(
    today_str: str,
    tz_name: str,
    horizon_start: str,
    horizon_end: str,
    constraint_table: str,
    history: list[tuple[str, str]],
    message: str,
) -> str:
    hist = "\n".join(f"{who}: {text}" for who, text in history[-6:])
    return f"""\
Today: {today_str} (timezone {tz_name})
Planning horizon: {horizon_start} to {horizon_end} (inclusive)

Current constraints:
{constraint_table or '(none)'}

Recent conversation:
{hist or '(none)'}

New user message:
{message}
"""


EXPLAINER_SYSTEM = """\
You are the conflict explainer of a personal monthly scheduler. The constraint
solver found the user's requests IMPOSSIBLE to satisfy together. You receive
the near-minimal set of conflicting requests (with their constraints) and a
time-capacity summary.

Produce JSON with:
- `explanation`: 2-4 sentences, in English, explaining WHY these requests clash,
  with concrete arithmetic when relevant (e.g. "10h of sleep + 14h of work = 24h:
  no room left for meals").
  Mention [DEFAULT] constraints explicitly if they participate.
- `conflicting_request_ids`: echo the request ids you were given.
- `proposals`: EXACTLY 2 or 3 concrete compromises, each with:
  - `description`: one sentence in English ("Reduce sleep to 8h per night").
  - `patch`: the machine-applicable actions (MODIFY with full replacement
    payload, or DELETE) implementing that compromise. Use the exact
    constraint ids provided. Prefer softening (strength=soft) or reducing
    quantities over deleting.
Keep proposals realistic and minimal: change as little as possible.
"""
