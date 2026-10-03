"""Cost summary and attribution routes."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request

from ..cost.attribution import CostBreakdown, attribute
from ..trace.collector import TraceCollector

router = APIRouter(tags=["cost"])


@router.get("/cost/summary")
async def cost_summary(request: Request):
    """Get a high-level cost summary across all traces."""
    collector = request.app.state.collector

    servers = await collector.get_mcp_server_stats()
    tools = await collector.get_tool_stats()

    total_calls = sum(s["call_count"] for s in servers)
    total_errors = sum(s["error_count"] for s in servers)
    total_data_bytes = sum(s["total_result_bytes"] or 0 for s in servers)

    # Estimate total cost using MVP attribution
    total_cost_usd = round(total_data_bytes * (0.001 / (10 * 1024)), 6)

    return {
        "total_tool_calls": total_calls,
        "total_errors": total_errors,
        "total_result_bytes": total_data_bytes,
        "estimated_cost_usd": total_cost_usd,
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

    return {
        "trace_id": trace_id,
        "total_cost_usd": breakdown.total_cost_usd,
        "input_tokens": breakdown.input_tokens,
        "output_tokens": breakdown.output_tokens,
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

        _, spans = trace_result
        breakdown = attribute(spans, pricing_func=None)

        trend.append({
            "trace_id": trace_id,
            "timestamp": trace["timestamp"],
            "total_cost_usd": breakdown.total_cost_usd,
            "span_count": trace["span_count"],
            "error_count": trace["error_count"],
            "by_tool": breakdown.by_tool,
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