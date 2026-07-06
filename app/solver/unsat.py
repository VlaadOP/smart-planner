"""Extraction du cœur d'infaisabilité au niveau des requêtes utilisateur.

CP-SAT renvoie un ensemble d'assomptions *suffisant* pour l'infaisabilité
(sur-approximation). On le rétrécit par deletion-filtering : les solves étant
sous la seconde à cette échelle, on re-teste chaque membre. Résultat : un
ensemble quasi minimal de source_request_id en conflit, que l'explainer LLM
traduit ensuite en langage naturel."""
from __future__ import annotations

from ortools.sat.python import cp_model

from app.compiler.compile import CompiledModel
from app.config import Settings
from app.solver.model import build_model


def _solve_assuming(
    cm: CompiledModel, cfg: Settings, enforced: list[str]
) -> tuple[int, list[str]]:
    built = build_model(cm, cfg, prev=None, enforced=set(enforced))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = cfg.solver_core_time_limit_s
    solver.parameters.num_search_workers = cfg.solver_workers
    solver.parameters.random_seed = cfg.solver_seed
    status = solver.Solve(built.model)
    core: list[str] = []
    if status == cp_model.INFEASIBLE:
        indices = solver.SufficientAssumptionsForInfeasibility()
        core = sorted({built.lit_index_to_request[i] for i in indices if i in built.lit_index_to_request})
    return status, core


def find_core(cm: CompiledModel, cfg: Settings) -> list[str]:
    """Retourne une liste quasi minimale de requêtes en conflit (vide si faisable)."""
    all_hard = sorted(cm.hard_request_ids)
    if not all_hard:
        return []
    status, core = _solve_assuming(cm, cfg, all_hard)
    if status != cp_model.INFEASIBLE:
        return []
    if not core:
        core = list(all_hard)

    # Deletion filtering : retire un membre ; si toujours infaisable sans lui,
    # il n'est pas nécessaire au conflit.
    changed = True
    while changed:
        changed = False
        for rid in list(core):
            if len(core) <= 1:
                break
            test = [r for r in core if r != rid]
            st, sub = _solve_assuming(cm, cfg, test)
            if st == cp_model.INFEASIBLE:
                core = sub if sub else test
                changed = True
                break
    return sorted(core)
