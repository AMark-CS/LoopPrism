"""Session inspector API: list, search, read, analyse, resume and delete agent sessions.

These routes expose the content of your coding sessions (prompts, code, tool
output), so they only answer requests that really come from this machine's own
dashboard: a loopback ``Host`` and, when a browser sends one, a same-origin
``Origin``. That blocks other web pages from reading or deleting sessions.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from ..sessions import actions, agents, analysis, context
from ..sessions.store import READ_ONLY_AGENTS
from ..sessions import models as M
from ..sessions.store import SessionStore

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def local_only(request: Request) -> None:
    host_header = request.headers.get("host") or ""
    if urlparse(f"//{host_header}").hostname not in LOOPBACK_HOSTS:
        raise HTTPException(status_code=403, detail="Sessions are only available on this machine")
    origin = request.headers.get("origin")
    if origin and urlparse(origin).netloc != host_header:
        raise HTTPException(status_code=403, detail="Cross-origin requests are not accepted")


router = APIRouter(prefix="/sessions", tags=["sessions"], dependencies=[Depends(local_only)])


def get_store(request: Request) -> SessionStore:
    store = getattr(request.app.state, "sessions", None)
    if store is None:
        db_path = getattr(getattr(request.app.state, "collector", None), "db_path", None)
        index = os.path.join(os.path.dirname(os.path.abspath(db_path)), "sessions-index.db") if db_path and db_path != ":memory:" else None
        store = request.app.state.sessions = SessionStore(index)
    return store


async def _load(request: Request, session_id: str):
    store = get_store(request)
    if "~" in session_id:  # a subagent transcript: "<session>~<agent>"
        parent, _, agent_id = session_id.partition("~")
        ps = await asyncio.to_thread(store.load_subagent, parent, agent_id)
    else:
        ps = await asyncio.to_thread(store.load, session_id)
    if ps is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return ps


@router.get("")
async def list_sessions(
    request: Request,
    agent: Optional[str] = None,
    q: Optional[str] = None,
    project: Optional[str] = None,
    limit: int = Query(300, ge=1, le=2000),
    offset: int = Query(0, ge=0),
):
    store = get_store(request)
    progress = await asyncio.to_thread(store.refresh, 1.5)
    rows = await asyncio.to_thread(store.list, agent, q, project, limit, offset)
    return {"sessions": rows, "total": store.count(), "pending": progress["pending"]}


@router.get("/cost/overview")
async def cost_overview(request: Request, days: int = Query(30, ge=0, le=3650), agent: Optional[str] = None):
    """What the agents cost, across every session on this machine (``days=0``: all time)."""
    store = get_store(request)
    await asyncio.to_thread(store.refresh, 5.0)
    since = None
    if days:
        from datetime import datetime, timedelta, timezone

        since = (datetime.now(timezone.utc) - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    out = await asyncio.to_thread(store.cost_overview, since, agent)
    out["days"] = days
    out["pending"] = store.pending
    return out


@router.get("/projects")
async def list_projects(request: Request):
    return {"projects": await asyncio.to_thread(get_store(request).projects)}


@router.get("/{session_id}")
async def get_session(session_id: str, request: Request):
    ps = await _load(request, session_id)
    meta = ps.meta.to_dict()
    meta["read_only"] = ps.meta.agent in READ_ONLY_AGENTS
    meta["resume_command"] = None if "~" in session_id or meta["read_only"] else actions.resume_command(ps.meta)
    return {"session": meta, "stats": context.stats(ps), "findings": analysis.findings(ps)}


@router.get("/{session_id}/agents")
async def get_agents(session_id: str, request: Request):
    """The main agent and the subagents it spawned, with cost, time and handoffs."""
    if "~" in session_id:
        raise HTTPException(status_code=400, detail="Open the agent tree from the parent session")
    ps = await _load(request, session_id)
    return await asyncio.to_thread(agents.build, ps)


@router.get("/{session_id}/events")
async def get_events(
    session_id: str,
    request: Request,
    offset: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=5000),
    kinds: Optional[str] = None,
    q: Optional[str] = None,
    preview: Optional[int] = Query(None, ge=0, le=100_000),
):
    ps = await _load(request, session_id)
    wanted = set(kinds.split(",")) if kinds else None
    needle = q.lower() if q else None
    pool = [
        e for e in ps.events
        if (wanted is None or e.kind in wanted)
        and (needle is None or needle in e.text.lower() or needle in (e.tool_name or "").lower())
    ]
    page = pool[offset: offset + limit]
    return {"total": len(pool), "events": [e.to_dict(preview) for e in page]}


@router.get("/{session_id}/events/{idx}")
async def get_event(session_id: str, idx: int, request: Request):
    ps = await _load(request, session_id)
    if idx < 0 or idx >= len(ps.events):
        raise HTTPException(status_code=404, detail="Event not found")
    return ps.events[idx].to_dict()


@router.get("/{session_id}/trajectory")
async def get_trajectory(session_id: str, request: Request):
    ps = await _load(request, session_id)
    turns: dict[int, dict[str, Any]] = {}
    for e in ps.events:
        if e.turn and e.turn not in turns and e.kind == M.USER and not e.sidechain:
            turns[e.turn] = {"turn": e.turn, "first_event": e.idx, "ts": e.ts, "text": e.text[:200]}
    steps = [
        {
            "step": s.index, "turn": s.turn, "model": s.model, "ts": s.ts, "sidechain": s.sidechain,
            "first_event": s.first_event, "input_tokens": s.total_input, "output_tokens": s.output_tokens,
            "cost_usd": s.cost_usd, "model_ms": s.model_ms, "thinking_ms": s.thinking_ms, "tools_ms": s.tools_ms,
        }
        for s in ps.steps if s.model != "<synthetic>"
    ]
    return {
        "turns": list(turns.values()),
        "steps": steps,
        "findings": analysis.findings(ps),
        "event_count": len(ps.events),
    }


@router.get("/{session_id}/context")
async def get_context(session_id: str, request: Request):
    ps = await _load(request, session_id)

    def build():
        return {"stats": context.stats(ps), "trend": context.trend(ps)}

    return await asyncio.to_thread(build)


@router.get("/{session_id}/context/{step}")
async def get_context_step(session_id: str, step: int, request: Request, detail: bool = True):
    ps = await _load(request, session_id)
    if step < 0 or step >= len(ps.steps):
        raise HTTPException(status_code=404, detail="Step not found")
    return await asyncio.to_thread(context.step_context, ps, step, detail)


@router.get("/{session_id}/cost")
async def get_cost(session_id: str, request: Request):
    ps = await _load(request, session_id)
    return await asyncio.to_thread(analysis.cost_breakdown, ps)


@router.get("/{session_id}/timing")
async def get_timing(session_id: str, request: Request):
    ps = await _load(request, session_id)
    return analysis.timing(ps)


@router.get("/{session_id}/export.md", response_class=PlainTextResponse)
async def export_markdown(session_id: str, request: Request):
    ps = await _load(request, session_id)
    return PlainTextResponse(actions.export_markdown(ps), media_type="text/markdown; charset=utf-8")


@router.post("/{session_id}/resume")
async def resume(session_id: str, request: Request, terminal: bool = False):
    if "~" in session_id:
        raise HTTPException(status_code=400, detail="Subagent transcripts cannot be resumed on their own")
    ps = await _load(request, session_id)
    if ps.meta.agent in READ_ONLY_AGENTS:
        raise HTTPException(status_code=400, detail="Resume this session from its own app; LoopPrism only reads it")
    command = actions.resume_command(ps.meta)
    if terminal:
        try:
            await asyncio.to_thread(actions.open_in_terminal, command)
        except Exception as err:  # surfaced to the UI
            raise HTTPException(status_code=500, detail=str(err))
    return {"command": command, "opened": terminal}


@router.post("/{session_id}/delete")
async def delete_session(session_id: str, request: Request):
    if "~" in session_id:
        raise HTTPException(status_code=400, detail="Delete the parent session instead")
    store = get_store(request)
    row = await asyncio.to_thread(store.find, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row["agent"] in READ_ONLY_AGENTS:
        raise HTTPException(status_code=400, detail="Delete this session from its own app; LoopPrism only reads it")
    try:
        dest = await asyncio.to_thread(actions.trash, row["path"], store.allowed_roots())
    except PermissionError as err:
        raise HTTPException(status_code=403, detail=str(err))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Session file is already gone")
    store.forget(row["path"])
    return {"trashed": dest}
