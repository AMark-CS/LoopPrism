"""Trace listing and detail routes."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(tags=["traces"])


@router.get("/traces")
async def list_traces(
    request: Request,
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    mcp_server: Optional[str] = None,
    time_from: Optional[str] = None,
    time_to: Optional[str] = None,
):
    """List recent traces."""
    collector = request.app.state.collector

    from_dt = None
    to_dt = None
    if time_from:
        from_dt = datetime.fromisoformat(time_from)
    if time_to:
        to_dt = datetime.fromisoformat(time_to)

    traces = await collector.list_traces(
        limit=limit,
        offset=offset,
        mcp_server=mcp_server,
        time_from=from_dt,
        time_to=to_dt,
    )

    return {
        "traces": traces,
        "limit": limit,
        "offset": offset,
    }


@router.get("/traces/{trace_id}")
async def get_trace(trace_id: str, request: Request):
    """Get a single trace with all its spans."""
    collector = request.app.state.collector
    result = await collector.get_trace(trace_id)

    if result is None:
        raise HTTPException(status_code=404, detail="Trace not found")

    trace, spans = result
    return {"trace": trace, "spans": spans}


@router.delete("/traces")
async def clear_traces(request: Request):
    """Delete all traces. Use with caution."""
    collector = request.app.state.collector
    deleted = await collector.cleanup_old_traces(retention_days=0)
    return {"deleted": deleted}
