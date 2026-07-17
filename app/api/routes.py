"""Endpoints FastAPI. Le solveur et le LLM tournent dans l'executor (threads)
pour garder uvicorn réactif ; un verrou par session sérialise les mutations."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException, Request, Response

from app.llm.client import LLMError, LLMUnavailableError
from app.schemas.api import (
    ChatRequest,
    ChatResponse,
    ChatTurn,
    SessionCreateRequest,
    SessionView,
)
from app.defaults.realism import default_constraints
from app.export.ics import IcsExporter
from app.schemas.schedule import ScheduleDiff
from app.services import constraint_views, resolve
from app.store.constraint_store import apply_actions
from app.store.session import SessionState

router = APIRouter(prefix="/api")


def _deps(request: Request):
    return request.app.state


def _get_state(request: Request, session_id: str) -> SessionState:
    state = _deps(request).store.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session inconnue")
    return state


def _session_view(state: SessionState) -> SessionView:
    from datetime import timedelta

    return SessionView(
        session_id=state.session_id,
        horizon_start=state.horizon_start,
        horizon_end=state.horizon_start + timedelta(days=state.horizon_days - 1),
        timezone=state.timezone,
        solver_status=state.solver_status,
        schedule=state.last_good_schedule,
        constraints=constraint_views(state),
        chat_history=state.chat_history,
        infeasibility=state.last_infeasibility,
        validated_at=state.validated_at,
    )


def _chat_response(state: SessionState, message: str, diff: ScheduleDiff | None = None) -> ChatResponse:
    return ChatResponse(
        assistant_message=message,
        solver_status=state.solver_status,
        schedule=state.last_good_schedule,
        diff=diff or ScheduleDiff(),
        infeasibility=state.last_infeasibility,
        constraints=constraint_views(state),
    )


async def _resolve_async(request: Request, state: SessionState) -> tuple[str, ScheduleDiff]:
    deps = _deps(request)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, resolve, state, deps.cfg, deps.explain_fn)


@router.post("/sessions", response_model=SessionView)
async def create_session(request: Request, body: SessionCreateRequest | None = None):
    deps = _deps(request)
    start = (body.horizon_start if body else None) or date.today()
    state = deps.store.create(start, deps.cfg.horizon_days, deps.cfg.timezone)
    state.constraints = default_constraints()
    await _resolve_async(request, state)
    deps.store.save(state)
    return _session_view(state)


@router.get("/sessions/{session_id}", response_model=SessionView)
async def get_session(request: Request, session_id: str):
    return _session_view(_get_state(request, session_id))


@router.get("/sessions/{session_id}/schedule")
async def get_schedule(request: Request, session_id: str):
    state = _get_state(request, session_id)
    return state.last_good_schedule or {"blocks": [], "solver_status": state.solver_status}


@router.get("/sessions/{session_id}/constraints")
async def get_constraints(request: Request, session_id: str):
    return constraint_views(_get_state(request, session_id))


@router.post("/sessions/{session_id}/chat", response_model=ChatResponse)
async def chat(request: Request, session_id: str, body: ChatRequest):
    deps = _deps(request)
    state = _get_state(request, session_id)
    async with deps.locks[session_id]:
        state.chat_history.append(ChatTurn(who="user", text=body.message))
        rid = state.new_request_id(body.message)
        loop = asyncio.get_running_loop()
        try:
            parse_result = await loop.run_in_executor(None, deps.parse_fn, state, body.message)
        except LLMUnavailableError as e:
            msg = f"⚠️ {e}"
            state.chat_history.append(ChatTurn(who="assistant", text=msg))
            deps.store.save(state)
            return _chat_response(state, msg)
        except LLMError as e:
            msg = f"I couldn't interpret the request: {e}"
            state.chat_history.append(ChatTurn(who="assistant", text=msg))
            deps.store.save(state)
            return _chat_response(state, msg)

        merge = apply_actions(state, parse_result.actions, rid)
        message = parse_result.assistant_message
        diff = ScheduleDiff()

        if merge.clarification:
            message = merge.clarification
        elif merge.errors and merge.applied == 0:
            message = " ".join(merge.errors)
        elif merge.applied:
            status, diff = await _resolve_async(request, state)
            if status == "INFEASIBLE" and state.last_infeasibility:
                message += " ⚠️ " + state.last_infeasibility.explanation

        state.chat_history.append(ChatTurn(who="assistant", text=message))
        deps.store.save(state)
        return _chat_response(state, message, diff)


@router.delete("/sessions/{session_id}/constraints/{constraint_id}", response_model=ChatResponse)
async def delete_constraint(request: Request, session_id: str, constraint_id: str):
    deps = _deps(request)
    state = _get_state(request, session_id)
    async with deps.locks[session_id]:
        target = next((c for c in state.constraints if c.id == constraint_id and c.active), None)
        if target is None:
            raise HTTPException(status_code=404, detail="Contrainte inconnue")
        target.active = False
        _, diff = await _resolve_async(request, state)
        deps.store.save(state)
        return _chat_response(state, f"Constraint “{target.label}” deleted.", diff)


@router.post("/sessions/{session_id}/relaxations/{index}/accept", response_model=ChatResponse)
async def accept_relaxation(request: Request, session_id: str, index: int):
    deps = _deps(request)
    state = _get_state(request, session_id)
    async with deps.locks[session_id]:
        report = state.last_infeasibility
        if report is None or not (0 <= index < len(report.proposals)):
            raise HTTPException(status_code=409, detail="No relaxation proposal at this index")
        proposal = report.proposals[index]
        rid = state.new_request_id(f"[relaxation accepted] {proposal.description}")
        merge = apply_actions(state, proposal.patch, rid)
        if merge.applied == 0:
            raise HTTPException(status_code=422, detail="; ".join(merge.errors) or "Patch not applicable")
        _, diff = await _resolve_async(request, state)
        message = f"Trade-off applied: {proposal.description}"
        state.chat_history.append(ChatTurn(who="assistant", text=message))
        deps.store.save(state)
        return _chat_response(state, message, diff)


@router.post("/sessions/{session_id}/export")
async def export_schedule(request: Request, session_id: str, include_defaults: bool = False):
    deps = _deps(request)
    state = _get_state(request, session_id)
    if state.last_good_schedule is None or not state.last_good_schedule.blocks:
        raise HTTPException(status_code=409, detail="No feasible schedule to export")
    if state.solver_status == "INFEASIBLE":
        raise HTTPException(
            status_code=409,
            detail="The current schedule is in conflict: resolve it before exporting.",
        )
    payload = IcsExporter().export(state.last_good_schedule, state.session_id, include_defaults)
    state.validated_at = datetime.now(timezone.utc)
    deps.store.save(state)
    return Response(
        content=payload,
        media_type="text/calendar",
        headers={"Content-Disposition": 'attachment; filename="smart-planner.ics"'},
    )
