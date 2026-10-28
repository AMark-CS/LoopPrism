"""Cost summary and attribution routes."""

from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, Query, Request

from ..cost.attribution import CostBreakdown, attribute
from ..cost.pricing import PRICING_AS_OF, PRICING_SOURCES, usage_cost_parts
from ..trace.collector import TraceCollector

router = APIRouter(tags=["cost"])

TYPE_LABELS = {
    "input": "Uncached input",
    "cache_read": "Cache reads",
    "cache_write": "Cache writes",
    "output": "Output",
}


def run_usage(trace: dict[str, Any]) -> Optional[list[dict[str, Any]]]:
    """Token usage an agent reported for this run (stored when its turn ended)."""
    try:
        rows = json.loads(trace.get("metadata") or "{}").get("usage")
    except (TypeError, ValueError, AttributeError):
        return None
    return rows if isinstance(rows, list) and rows else None


def agent_cost(trace: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Cost of an agent run by model and by token type, from its real token usage."""
    by_type = {k: {"key": k, "label": v, "tokens": 0, "cost_usd": 0.0} for k, v in TYPE_LABELS.items()}
    models = []
    unpriced = []
    for u in rows:
        model = str(u.get("model") or "unknown")
        tokens = {
            "input": int(u.get("input_tokens") or 0),
            "cache_read": int(u.get("cache_read_tokens") or 0),
            "cache_write": int(u.get("cache_write_tokens") or 0) + int(u.get("cache_write_1h_tokens") or 0),
            "output": int(u.get("output_tokens") or 0),
        }
        parts = usage_cost_parts(model, u)
        for k, n in tokens.items():
            by_type[k]["tokens"] += n
            if parts is not None:
                by_type[k]["cost_usd"] += parts[k]
        if parts is None:
            unpriced.append(model)
        models.append({
            "model": model, "calls": int(u.get("calls") or 0), "tokens": tokens,
            "cost_usd": None if parts is None else round(sum(parts.values()), 6),
        })
    return {
        "by_model": models,
        "by_token_type": [{**v, "cost_usd": round(v["cost_usd"], 6)} for v in by_type.values() if v["tokens"]],
        "unpriced_models": unpriced,
        "pricing_as_of": PRICING_AS_OF,
    }


@router.get("/cost/summary")
async def cost_summary(request: Request):
    """Get a high-level cost summary across all traces."""
    collector = request.app.state.collector

    servers = await collector.get_mcp_server_stats()
    tools = await collector.get_tool_stats()

    total_calls = sum(s["call_count"] for s in servers)
    total_errors = sum(s["error_count"] for s in servers)
    total_data_bytes = sum(s["total_result_bytes"] or 0 for s in servers)

    # Cost comes from the token usage agents report, priced at current API
    # prices. MCP-only traffic has no token counts, so it adds nothing here.
    totals = await collector.get_run_totals()

    return {
        "run_count": totals["run_count"],
        "priced_runs": totals["priced_runs"],
        "tool_call_count": totals["tool_call_count"],
        "pricing_as_of": PRICING_AS_OF,
        "pricing_sources": PRICING_SOURCES,
        "total_tool_calls": total_calls,
        "total_errors": total_errors,
        "total_result_bytes": total_data_bytes,
        "estimated_cost_usd": round(totals["total_cost_usd"], 4),
        "mcp_servers": servers,
        "tools": tools,
    }


@router.get("/cost/trace/{trace_id}")
async def cost_trace(trace_id: str, request: Request):
    """Get cost breakdown for a specific trace.

    Uses the attribution engine to attribute token costs to each MCP tool.
    """
    collector: TraceCollector = request.app.state.collector

    result = await collector.get_trace(trace_id)
    if result is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Trace not found")

    trace, spans = result

    # Run attribution
    breakdown = attribute(spans, pricing_func=None)

    # An agent run reports real token usage; that, not the bytes-based estimate
    # below, is what it cost.
    rows = run_usage(trace)
    agent = agent_cost(trace, rows) if rows else None
    note = None
    if agent is None and trace.get("root_span_type") == "agent.run":
        note = (
            "Cost is added when the agent finishes its turn."
            if trace.get("status") == "running"
            else "This run reported no token usage."
        )

    return {
        "agent_usage": agent,
        "note": note,
        "trace_id": trace_id,
        "total_cost_usd": (trace.get("total_cost_usd") or 0.0) if agent else breakdown.total_cost_usd,
        "input_tokens": sum(t["tokens"] for t in agent["by_token_type"] if t["key"] != "output") if agent else breakdown.input_tokens,
        "output_tokens": sum(t["tokens"] for t in agent["by_token_type"] if t["key"] == "output") if agent else breakdown.output_tokens,
        "mcp_tool_cost_usd": breakdown.mcp_tool_cost,
        "llm_cost_usd": breakdown.llm_cost,
        "by_server": breakdown.by_server,
        "by_tool": breakdown.by_tool,
        "items": [
            {
                "source": item.source,
                "source_type": item.source_type,
                "cost_usd": item.cost_usd,
                "proportion": round(item.proportion, 4),
                "input_tokens": item.input_tokens,
                "output_tokens": item.output_tokens,
                "latency_ms": item.latency_ms,
                "result_bytes": item.result_bytes,
            }
            for item in breakdown.items
        ],
    }


@router.get("/cost/trend")
async def cost_trend(
    request: Request,
    limit: int = Query(50, ge=1, le=500, description="Number of traces"),
):
    """Get cost trend across recent traces.

    Returns traces ordered by timestamp with estimated costs.
    """
    collector: TraceCollector = request.app.state.collector

    traces = await collector.list_traces(limit=limit)

    trend = []
    for trace in traces:
        trace_id = trace["id"]
        trace_result = await collector.get_trace(trace_id)
        if trace_result is None:
            continue

        full_trace, spans = trace_result
        if run_usage(full_trace):  # an agent run: its real, priced token usage
            total, by_tool = full_trace.get("total_cost_usd") or 0.0, {}
        else:
            breakdown = attribute(spans, pricing_func=None)
            total, by_tool = breakdown.total_cost_usd, breakdown.by_tool

        trend.append({
            "trace_id": trace_id,
            "timestamp": trace["timestamp"],
            "total_cost_usd": total,
            "span_count": trace["span_count"],
            "error_count": trace["error_count"],
            "by_tool": by_tool,
        })

    return {"trends": trend}


@router.get("/cost/top-tools")
async def top_tools(
    request: Request,
    limit: int = Query(10, ge=1, le=100),
    time_from: Optional[str] = Query(None, description="ISO datetime"),
    time_to: Optional[str] = Query(None, description="ISO datetime"),
):
    """Get the most expensive MCP tools by attributed cost."""
    collector: TraceCollector = request.app.state.collector

    # Get all tool stats (aggregated)
    tools = await collector.get_tool_stats()

    # Sort by call count * avg latency as a proxy for cost
    ranked = sorted(
        tools,
        key=lambda t: (t["call_count"] or 0) * (t["avg_result_bytes"] or 0),
        reverse=True,
    )

    return {"tools": ranked[:limit]}