# Smart Planner

Smart monthly planner for a single person: you describe your constraints in
natural language ("1h break per day", "fixed meeting Tuesday at 2pm", "10h of
sleep"), an LLM translates them into structured constraints, an optimization
solver builds a schedule in **15-minute blocks over a 30-day rolling window**,
and you validate the result before exporting it to `.ics`.

## Architecture

```
natural language ──> Gemini (structured output) ──> Pydantic IR ──> compiler ──> CP-SAT
                                                        ▲                          │
              explanation + trade-offs <── unsat core (assumptions) <── INFEASIBLE
                                                                            │
                       FastAPI + FullCalendar (validation) <── schedule ◄──┘
                                     │
                                 .ics export
```

- **Constraint IR** (`app/schemas/ir.py`): 6 types — FixedEvent, FlexibleTask,
  RecurringBudget, Blackout, BufferRule, MaxStretch — in human time ("HH:MM"
  aligned to 15 min). It's the only bridge between the LLM and the solver:
  `app/llm` never imports OR-Tools, `app/solver` never imports the Gemini SDK.
- **Gemini boundary** (`app/schemas/actions.py`): flat envelope (no `anyOf`),
  systematic Pydantic re-validation + repair loop. ADD / MODIFY / DELETE /
  CLARIFY actions — the parser receives the table of current constraints and
  targets real ids ("actually, delete Tuesday's meeting"). The assistant always
  replies in English (French or English input is understood).
- **Solver** (`app/solver/`): CP-SAT, optional intervals + a global `NoOverlap`
  (~150–400 intervals after recurrence expansion). Tiered objective: user soft
  ≫ realism defaults ≫ stability (blocks moved vs previous solution) ≫ preferred
  windows. Re-solves < 1 s thanks to hints.
- **Infeasibility**: per-request assumption literals → unsat core shrunk by
  deletion-filtering → natural-language Gemini explanation with 2-3 one-click
  trade-offs. The last feasible schedule stays on screen: the system never
  crashes.
- **Realism defaults** (`app/defaults/realism.py`): 8h sleep/night, meals, no
  night work, max 4h of work in a row, weekend rest — all SOFT and overridable
  with a single sentence.
- **Validation before export**: the solver and the LLM operate in isolation
  (JSON sessions on disk); only `POST /export` produces an external artifact
  (`.ics` with deterministic UIDs — re-importing updates instead of duplicating).

## Quick start

Requirements: **Python ≥ 3.11** and **git**. You also need a **Gemini API key**
(free): create one in 30 s at https://aistudio.google.com/apikey.

### 1. Get the code

```bash
git clone https://github.com/<your-user>/smart-planner.git
cd smart-planner
```

### 2. Install

<details open>
<summary><b>macOS / Linux</b></summary>

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # then open .env and paste your key
```
</details>

<details>
<summary><b>Windows (PowerShell)</b></summary>

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env         # then open .env and paste your key
```
</details>

In `.env`, replace `your-gemini-api-key` with your Gemini key.

### 3. Run

```bash
uvicorn app.main:app --port 8000
```

Open http://127.0.0.1:8000: chat on the left, a FullCalendar view
(month/week/day, 15-min granularity) on the right. Added blocks flash green,
moved blocks flash orange. On a conflict, a banner explains the blocking
requests and proposes clickable trade-offs.

> Once the venv is activated (`source .venv/bin/activate` or `Activate.ps1`),
> the `python`, `pip`, `uvicorn` and `pytest` commands point to the venv — no
> need to prefix them with the full path.

## Tests

```bash
pytest              # offline (LLM mocked/goldens) — no key required
pytest -m live      # real Gemini smoke test (key required)
```

- The schedule is checked by a **solver-independent validator**
  (`app/solver/validate.py`).
- Test solves are deterministic (1 worker, fixed seed).
- Golden tests (`tests/golden/`) pin the LLM ↔ server contract;
  `scripts/record_goldens.py` re-records real Gemini outputs.

## API

| Endpoint | Role |
|---|---|
| `POST /api/sessions` | create a session (realism defaults + initial solve) |
| `POST /api/sessions/{id}/chat` | NL message → parse → merge → re-solve → schedule + diff |
| `GET /api/sessions/{id}` / `.../schedule` / `.../constraints` | read |
| `DELETE /api/sessions/{id}/constraints/{cid}` | deactivate a constraint + re-solve |
| `POST /api/sessions/{id}/relaxations/{n}/accept` | apply a proposed trade-off |
| `POST /api/sessions/{id}/export` | validate and download the `.ics` (`?include_defaults=true` to include sleep/meals) |

## Known limitations (v1)

- Sliding window anchored at session creation (no daily re-anchoring).
- Travel buffer applied to every located event (no "same location" distinction).
- `MaxStretch` encoded in a simplified v1 (size cap + gap between blocks of the same category).
- Google Calendar API export: not included (the `app/export/base.py` interface is ready).
