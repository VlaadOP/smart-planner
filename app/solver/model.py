"""Construction du modèle CP-SAT à partir du CompiledModel.

Encodage : intervalles optionnels + un NoOverlap global (une personne = une
activité à la fois). Les contraintes HARD d'une requête utilisateur sont posées
sous le littéral d'assomption de cette requête (source_request_id), ce qui
permet d'extraire un cœur d'infaisabilité qui parle le langage de l'utilisateur.

Objectif (somme pondérée, paliers quasi lexicographiques) :
  violations soft utilisateur (poids 1-100, palier x100)
  + violations soft par défaut (palier x10)
  + stabilité : blocs déplacés vs solution précédente (x20)
  + fenêtres préférées manquées (x1)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from app.compiler.compile import ChunkSpec, CompiledModel
from app.config import Settings
from app.schemas.ir import Strength
from app.schemas.schedule import SolvedChunk


@dataclass
class ChunkVars:
    spec: ChunkSpec
    start: cp_model.IntVar
    size: cp_model.IntVar
    presence: cp_model.IntVar  # BoolVar
    interval: object


@dataclass
class BuiltModel:
    model: cp_model.CpModel
    chunk_vars: dict[str, ChunkVars]
    enforce_lits: dict[str, cp_model.IntVar]  # request_id -> littéral d'assomption
    lit_index_to_request: dict[int, str] = field(default_factory=dict)
    has_objective: bool = False


def _chunk_bounds(spec: ChunkSpec, n_slots: int) -> tuple[int, int]:
    """Bornes globales possibles [lo, hi) de l'intervalle, pour préfiltrer les paires."""
    if spec.fixed_start is not None:
        return spec.fixed_start, spec.fixed_start + spec.max_size
    if spec.windows:
        return min(a for a, _ in spec.windows), max(b for _, b in spec.windows)
    return 0, n_slots


def build_model(
    cm: CompiledModel,
    cfg: Settings,
    prev: dict[str, SolvedChunk] | None = None,
    enforced: set[str] | None = None,
) -> BuiltModel:
    """`enforced` : requêtes dont les contraintes HARD sont supposées (assomptions).
    None = toutes les requêtes hard. Les littéraux des requêtes non supposées
    restent libres (le solveur peut les désactiver) — c'est la base du
    deletion-filtering du cœur unsat."""
    m = cp_model.CpModel()
    n = cm.n_slots

    enforce_lits: dict[str, cp_model.IntVar] = {
        rid: m.NewBoolVar(f"enforce:{rid}") for rid in sorted(cm.hard_request_ids)
    }
    if enforced is None:
        enforced = set(cm.hard_request_ids)
    assumed = [enforce_lits[r] for r in sorted(enforced) if r in enforce_lits]
    m.AddAssumptions(assumed)
    lit_index_to_request = {enforce_lits[r].Index(): r for r in enforce_lits}

    def tier(is_default: bool) -> int:
        return cfg.tier_default_soft if is_default else cfg.tier_user_soft

    obj: list = []
    chunk_vars: dict[str, ChunkVars] = {}
    intervals = []

    for spec in cm.chunks:
        start = m.NewIntVar(0, n, f"{spec.key}:start")
        size = m.NewIntVar(spec.min_size, spec.max_size, f"{spec.key}:size")
        end = m.NewIntVar(0, n, f"{spec.key}:end")
        presence = m.NewBoolVar(f"{spec.key}:present")
        m.Add(end == start + size + spec.trailing_buffer)
        interval = m.NewOptionalIntervalVar(start, size + spec.trailing_buffer, end, presence, spec.key)
        intervals.append(interval)
        chunk_vars[spec.key] = ChunkVars(spec, start, size, presence, interval)

        if spec.fixed_start is not None:
            m.Add(start == spec.fixed_start)

        if spec.fixed_start is None and spec.windows is not None:
            # L'activité (hors tampon) doit tenir entièrement dans UNE fenêtre.
            in_w = []
            for j, (a, b) in enumerate(spec.windows):
                wb = m.NewBoolVar(f"{spec.key}:w{j}")
                m.Add(start >= a).OnlyEnforceIf([presence, wb])
                m.Add(start + size <= b).OnlyEnforceIf([presence, wb])
                in_w.append(wb)
            m.AddBoolOr(in_w).OnlyEnforceIf(presence)

        if spec.required_presence:
            if spec.strength == Strength.HARD:
                m.AddImplication(enforce_lits[spec.source_request_id], presence)
            else:
                obj.append(spec.weight * tier(spec.is_default) * (1 - presence))

        if spec.preferred:
            miss = m.NewBoolVar(f"{spec.key}:prefmiss")
            in_p = []
            for j, (a, b) in enumerate(spec.preferred):
                pb = m.NewBoolVar(f"{spec.key}:p{j}")
                m.Add(start >= a).OnlyEnforceIf(pb)
                m.Add(start + size <= b).OnlyEnforceIf(pb)
                in_p.append(pb)
            m.AddBoolOr(in_p + [presence.Not(), miss])
            obj.append(cfg.pref_window_weight * miss)

    m.AddNoOverlap(intervals)

    # --- Groupes (sommes / comptes / anti-symétrie) ---
    for g in cm.groups:
        cvs = [chunk_vars[k] for k in g.chunk_keys]
        lit = enforce_lits.get(g.source_request_id)
        present_sizes = []
        for cv in cvs:
            ps = m.NewIntVar(0, cv.spec.max_size, f"{cv.spec.key}:psize")
            m.Add(ps == cv.size).OnlyEnforceIf(cv.presence)
            m.Add(ps == 0).OnlyEnforceIf(cv.presence.Not())
            present_sizes.append(ps)

        if g.target_slots is not None:
            total = sum(present_sizes)
            if g.strength == Strength.HARD:
                m.Add(total == g.target_slots).OnlyEnforceIf(lit)
            else:
                short = m.NewIntVar(0, g.target_slots, f"{g.group_id}:short")
                m.Add(total + short >= g.target_slots)
                m.Add(total <= g.target_slots)
                obj.append(g.weight * tier(g.is_default) * short)

        if g.exact_count is not None:
            count = sum(cv.presence for cv in cvs)
            if g.strength == Strength.HARD:
                m.Add(count == g.exact_count).OnlyEnforceIf(lit)
            else:
                cshort = m.NewIntVar(0, g.exact_count, f"{g.group_id}:cshort")
                m.Add(count + cshort >= g.exact_count)
                m.Add(count <= g.exact_count)
                obj.append(g.weight * tier(g.is_default) * cshort)

        if g.ordered:
            for a, b in zip(cvs, cvs[1:]):
                m.AddImplication(b.presence, a.presence)
                m.Add(b.start >= a.start + a.size).OnlyEnforceIf([a.presence, b.presence])
                if g.min_start_gap:
                    # Soft : soit b démarre >= min_start_gap après a (jours distincts),
                    # soit on paie spread_penalty. Sans effet si l'un est absent.
                    far = m.NewBoolVar(f"{b.spec.key}:spread")
                    m.Add(b.start >= a.start + g.min_start_gap).OnlyEnforceIf(far)
                    crammed = m.NewBoolVar(f"{b.spec.key}:crammed")
                    m.AddBoolOr([far, a.presence.Not(), b.presence.Not(), crammed])
                    obj.append(cfg.spread_penalty * crammed)

    # --- Blackouts ---
    for bo in cm.blackouts:
        lit = enforce_lits.get(bo.source_request_id)
        for cv in chunk_vars.values():
            if bo.categories is not None and cv.spec.category not in bo.categories:
                continue
            if cv.spec.constraint_id == bo.constraint_id:
                continue
            lo, hi = _chunk_bounds(cv.spec, n)
            for r_idx, (a, b) in enumerate(bo.ranges):
                if hi <= a or lo >= b:
                    continue  # aucun chevauchement possible
                name = f"bo:{bo.constraint_id}:{cv.spec.key}:{r_idx}"
                left = m.NewBoolVar(name + ":l")
                right = m.NewBoolVar(name + ":r")
                m.Add(cv.start + cv.size <= a).OnlyEnforceIf(left)
                m.Add(cv.start >= b).OnlyEnforceIf(right)
                if bo.strength == Strength.HARD:
                    m.AddBoolOr([left, right, cv.presence.Not()]).OnlyEnforceIf(lit)
                else:
                    viol = m.NewBoolVar(name + ":v")
                    m.AddBoolOr([left, right, cv.presence.Not(), viol])
                    obj.append(bo.weight * tier(bo.is_default) * viol)

    # --- MaxStretch (v1 : taille de chunk plafonnée + écart entre chunks de même catégorie) ---
    for st in cm.stretches:
        lit = enforce_lits.get(st.source_request_id)
        matching = [cv for cv in chunk_vars.values() if cv.spec.category == st.category]
        for cv in matching:
            if cv.spec.min_size > st.max_slots or cv.spec.max_size > st.max_slots:
                if st.strength == Strength.HARD:
                    m.Add(cv.size <= st.max_slots).OnlyEnforceIf(lit)
                else:
                    over = m.NewBoolVar(f"st:{st.constraint_id}:{cv.spec.key}:over")
                    m.Add(cv.size <= st.max_slots).OnlyEnforceIf(over.Not())
                    obj.append(st.weight * tier(st.is_default) * over)
        for i in range(len(matching)):
            for j in range(i + 1, len(matching)):
                ci, cj = matching[i], matching[j]
                lo_i, hi_i = _chunk_bounds(ci.spec, n)
                lo_j, hi_j = _chunk_bounds(cj.spec, n)
                if hi_i + st.gap_slots <= lo_j or hi_j + st.gap_slots <= lo_i:
                    continue  # jamais assez proches pour violer l'écart
                name = f"st:{st.constraint_id}:{ci.spec.key}:{cj.spec.key}"
                s1 = m.NewBoolVar(name + ":s1")
                s2 = m.NewBoolVar(name + ":s2")
                m.Add(cj.start >= ci.start + ci.size + st.gap_slots).OnlyEnforceIf(s1)
                m.Add(ci.start >= cj.start + cj.size + st.gap_slots).OnlyEnforceIf(s2)
                clause = [s1, s2, ci.presence.Not(), cj.presence.Not()]
                if st.strength == Strength.HARD:
                    m.AddBoolOr(clause).OnlyEnforceIf(lit)
                else:
                    viol = m.NewBoolVar(name + ":v")
                    m.AddBoolOr(clause + [viol])
                    obj.append(st.weight * tier(st.is_default) * viol)

    # --- Stabilité vs solution précédente + hints ---
    if prev:
        for key, pb in prev.items():
            cv = chunk_vars.get(key)
            if cv is None:
                continue
            if 0 <= pb.start <= n:
                m.AddHint(cv.start, pb.start)
            m.AddHint(cv.presence, 1 if pb.present else 0)
            if cv.spec.min_size <= pb.size <= cv.spec.max_size:
                m.AddHint(cv.size, pb.size)
            if pb.present:
                moved = m.NewBoolVar(f"{key}:moved")
                m.Add(cv.start == pb.start).OnlyEnforceIf(moved.Not())
                obj.append(cfg.stability_weight * moved)

    if obj:
        m.Minimize(sum(obj))

    return BuiltModel(
        model=m,
        chunk_vars=chunk_vars,
        enforce_lits=enforce_lits,
        lit_index_to_request=lit_index_to_request,
        has_objective=bool(obj),
    )
