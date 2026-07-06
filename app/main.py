"""Fabrique de l'application FastAPI + montage du frontend statique.

`parse_fn` et `explain_fn` vivent sur app.state : les tests les remplacent par
des stubs, et le vrai Gemini n'est instancié qu'au premier appel (lazy)."""
from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import date
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import Settings, settings
from app.schemas.actions import ParseResult
from app.services import grid_for
from app.store.session import SessionState, SessionStore

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def _make_parse_fn(app: FastAPI):
    def parse(state: SessionState, message: str) -> ParseResult:
        from app.llm.client import GeminiClient
        from app.llm.parser import parse_message

        if getattr(app.state, "gemini_client", None) is None:
            app.state.gemini_client = GeminiClient(app.state.cfg)
        history = [(t.who, t.text) for t in state.chat_history[:-1]]
        return parse_message(
            app.state.gemini_client,
            message,
            [c for c in state.constraints if c.active],
            history,
            grid_for(state),
            today=date.today(),
        )

    return parse


def _make_explain_fn(app: FastAPI):
    def explain(state, core_request_ids, compiled):
        from app.llm.client import GeminiClient
        from app.llm.explainer import explain_infeasibility

        if getattr(app.state, "gemini_client", None) is None:
            app.state.gemini_client = GeminiClient(app.state.cfg)
        return explain_infeasibility(app.state.gemini_client, state, core_request_ids, compiled)

    return explain


def create_app(cfg: Settings = settings) -> FastAPI:
    app = FastAPI(title="Smart Planner", version="0.1.0")
    app.state.cfg = cfg
    app.state.store = SessionStore(cfg.sessions_dir)
    app.state.locks = defaultdict(asyncio.Lock)
    app.state.gemini_client = None
    app.state.parse_fn = _make_parse_fn(app)
    app.state.explain_fn = _make_explain_fn(app)
    app.include_router(router)
    if FRONTEND_DIR.exists():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
    return app


app = create_app()
