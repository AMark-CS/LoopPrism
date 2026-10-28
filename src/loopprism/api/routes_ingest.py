"""Ingest route for agent lifecycle events sent by Claude Code / Codex hooks."""

from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from ..trace.ingest import AgentIngestor

router = APIRouter(tags=["ingest"])

MAX_BODY_BYTES = 2 * 1024 * 1024


class AgentEvent(BaseModel):
    """One lifecycle event from an agent."""

    model_config = ConfigDict(extra="ignore")

    agent: str = Field(min_length=1, max_length=40)
    event: Literal[
        "session_start", "prompt", "tool", "tool_failure", "stop", "session_end"
    ]
    session_id: str = Field(min_length=1, max_length=200)
    turn_id: Optional[str] = None
    cwd: Optional[str] = None
    model: Optional[str] = None
    prompt: Optional[str] = None
    tool_name: Optional[str] = None
    tool_input: Optional[Any] = None
    tool_use_id: Optional[str] = None
    tool_response: Optional[Any] = None
    duration_ms: Optional[float] = None
    error: Optional[str] = None
    outcome: Optional[str] = None


class IngestBatch(BaseModel):
    events: list[AgentEvent] = Field(min_length=1, max_length=100)


@router.post("/ingest/events")
async def ingest_events(batch: IngestBatch, request: Request):
    """Record agent events. Called by hook scripts, never by a browser."""
    # Hooks are plain processes. A request carrying an Origin header comes from
    # a web page, which must not be able to write into the local trace store.
    if request.headers.get("origin"):
        raise HTTPException(status_code=403, detail="Browser requests are not accepted")
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large")

    ingestor: AgentIngestor = request.app.state.ingestor
    results = [await ingestor.handle(e.model_dump()) for e in batch.events]
    return {"accepted": len(results), "results": results}
