"""Explainer d'infaisabilité : cœur unsat -> explication NL + 2-3 relaxations.

Reçoit les requêtes en conflit (avec énoncés d'origine et contraintes), plus un
résumé arithmétique de capacité pour que le modèle puisse expliquer la
sur-souscription (« 10h de sommeil + 14h de travail = 24h »)."""
from __future__ import annotations

from app.compiler.compile import CompiledModel
from app.compiler.timegrid import SLOT_MINUTES
from app.llm.client import GeminiClient
from app.llm.parser import constraint_table
from app.llm.prompts import EXPLAINER_SYSTEM
from app.schemas.actions import InfeasibilityReport
from app.schemas.ir import Strength
from app.store.session import SessionState


def capacity_summary(cm: CompiledModel) -> str:
    """Minutes demandées (contraintes dures) vs minutes disponibles."""
    demanded = 0
    for g in cm.groups:
        if g.strength == Strength.HARD and g.target_slots:
            demanded += g.target_slots
    for c in cm.chunks:
        if c.required_presence and c.strength == Strength.HARD:
            demanded += c.min_size
    total = cm.n_slots
    return (
        f"Hard-demanded time: {demanded * SLOT_MINUTES} min "
        f"({demanded * SLOT_MINUTES / 60:.0f}h) over a horizon of "
        f"{total * SLOT_MINUTES} min ({total * SLOT_MINUTES / 60:.0f}h)."
    )


def explain_infeasibility(
    client: GeminiClient,
    state: SessionState,
    core_request_ids: list[str],
    cm: CompiledModel,
) -> InfeasibilityReport:
    sections = []
    for rid in core_request_ids:
        utterance = state.request_log.get(rid, "[realism default]")
        constraints = [c for c in state.constraints if c.source_request_id == rid and c.active]
        table = constraint_table(constraints)
        sections.append(f"Request {rid}:\n  user said: {utterance!r}\n  constraints:\n{table}")

    user = (
        "The following requests are jointly infeasible (near-minimal conflict set):\n\n"
        + "\n\n".join(sections)
        + "\n\n"
        + capacity_summary(cm)
        + "\n\nExplain the conflict and propose 2-3 relaxations. Respond in the "
        "language of the user's requests above."
    )
    report = client.structured(EXPLAINER_SYSTEM, user, InfeasibilityReport)
    # Le modèle doit renvoyer les ids qu'on lui a donnés ; on force la vérité côté serveur.
    report.conflicting_request_ids = core_request_ids
    return report
