# Smart Planner

Planificateur mensuel intelligent pour une personne : vous décrivez vos
contraintes en langage naturel (« 1h de pause par jour », « réunion fixe mardi à
14h », « 10h de sommeil »), un LLM les traduit en contraintes structurées, un
solveur d'optimisation construit un planning en **blocs de 15 minutes sur 30
jours glissants**, et vous validez le résultat avant de l'exporter en `.ics`.

## Architecture

```
langage naturel ──> Gemini (sortie structurée) ──> IR Pydantic ──> compilateur ──> CP-SAT
                                                        ▲                            │
                    explication + compromis <── cœur unsat (assomptions) <── INFEASIBLE
                                                                              │
                          FastAPI + FullCalendar (validation) <── planning ◄──┘
                                       │
                                  export .ics
```

- **IR de contraintes** (`app/schemas/ir.py`) : 6 types — FixedEvent,
  FlexibleTask, RecurringBudget, Blackout, BufferRule, MaxStretch — en heure
  humaine (« HH:MM » alignés 15 min). C'est le seul pont entre le LLM et le
  solveur : `app/llm` n'importe jamais OR-Tools, `app/solver` n'importe jamais
  le SDK Gemini.
- **Frontière Gemini** (`app/schemas/actions.py`) : enveloppe plate (pas
  d'`anyOf`), re-validation Pydantic systématique + boucle de réparation.
  Actions ADD / MODIFY / DELETE / CLARIFY — le parseur reçoit la table des
  contraintes courantes et cible les ids réels (« finalement supprime la
  réunion de mardi »).
- **Solveur** (`app/solver/`) : CP-SAT, intervalles optionnels + `NoOverlap`
  global (~150–400 intervalles après expansion des récurrences). Objectif à
  paliers : soft utilisateur ≫ défauts de réalisme ≫ stabilité (blocs déplacés
  vs solution précédente) ≫ fenêtres préférées. Re-solves < 1 s grâce aux hints.
- **Infaisabilité** : littéraux d'assomption par requête utilisateur → cœur
  unsat rétréci par deletion-filtering → explication Gemini en langage naturel
  avec 2-3 compromis applicables en un clic. Le dernier planning faisable reste
  affiché : le système ne crashe jamais.
- **Réalisme par défaut** (`app/defaults/realism.py`) : sommeil 8h/nuit, repas,
  pas de travail nocturne, max 4h de travail d'affilée, repos le week-end —
  tous SOFT et surchargeables d'une phrase.
- **Validation avant export** : le solveur et le LLM opèrent en isolation
  (sessions JSON sur disque) ; seul `POST /export` produit un artefact externe
  (`.ics` avec UIDs déterministes — un ré-import met à jour au lieu de dupliquer).

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
copy .env.example .env    # puis renseigner GEMINI_API_KEY
```

## Lancement

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

Ouvrez http://127.0.0.1:8000 : chat à gauche, calendrier FullCalendar
(mois/semaine/jour, granularité 15 min) à droite. Les blocs ajoutés clignotent
en vert, les blocs déplacés en orange. En cas de conflit, une bannière explique
les requêtes bloquantes et propose des compromis cliquables.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest              # offline (LLM mocké/goldens)
.\.venv\Scripts\python.exe -m pytest -m live      # smoke test Gemini réel (clé requise)
```

- Le planning est vérifié par un **validateur indépendant du solveur**
  (`app/solver/validate.py`).
- Les solves de test sont déterministes (1 worker, seed fixe).
- Les golden tests (`tests/golden/`) épinglent le contrat LLM ↔ serveur ;
  `scripts/record_goldens.py` ré-enregistre des sorties Gemini réelles.

## API

| Endpoint | Rôle |
|---|---|
| `POST /api/sessions` | crée une session (défauts de réalisme + solve initial) |
| `POST /api/sessions/{id}/chat` | message NL → parse → merge → re-solve → planning + diff |
| `GET /api/sessions/{id}` / `.../schedule` / `.../constraints` | lecture |
| `DELETE /api/sessions/{id}/constraints/{cid}` | désactive une contrainte + re-solve |
| `POST /api/sessions/{id}/relaxations/{n}/accept` | applique un compromis proposé |
| `POST /api/sessions/{id}/export` | valide et télécharge le `.ics` (`?include_defaults=true` pour inclure sommeil/repas) |

## Limites connues (v1)

- Fenêtre glissante ancrée à la création de session (pas de re-ancrage quotidien).
- Tampon trajet appliqué à tout événement localisé (pas de distinction « même lieu »).
- `MaxStretch` encodé en v1 simplifiée (plafond de taille + écart entre blocs de même catégorie).
- Export Google Calendar API : non inclus (l'interface `app/export/base.py` est prête).
