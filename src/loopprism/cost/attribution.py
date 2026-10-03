"""Cost attribution engine — maps token costs to MCP tool calls.

Algorithm
=========
A typical Agent interaction trace looks like:

    [LLM 1] tokens=5000 → produces tool_choice
    [MCP:database/query] ← tool result: 100KB
    [LLM 2] tokens=15000 → processes the query result
    [MCP:chart/generate] ← tool result: 200KB
    [LLM 3] tokens=3000 → final answer

The algorithm attributes LLM costs to MCP tools in two passes:

PASS 1 — Upstream attribution:
    Each tool_call is attributed a fraction of the LLM call that produced it.
    Split the LLM's input tokens evenly across all tool calls it triggered.

PASS 2 — Downstream attribution:
    A tool's result feeds into the NEXT LLM call as context.
    The downstream LLM's cost is attributed proportionally to the tool
    based on the result size (as a proxy for how much context the tool added).

Example:
    LLM 2 has 15000 input tokens. MCP:database/query returned 100KB.
    MCP:chart/generate returned 200KB. Total tool result = 300KB.

    database/query gets: 100/300 × cost(LLM 2) = 33%
    chart/generate gets: 200/300 × cost(LLM 2) = 67%

The sum of attributed costs should roughly equal total LLM spend.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class CostItem:
    """Cost attributed to a single source."""

    source: str  # e.g. "MCP:database/query" | "LLM:thinking"
    source_type: str  # "mcp_tool" | "llm" | "other"

    # Token counts (may be estimated)
    input_tokens: int = 0
    output_tokens: int = 0

    # Cost breakdown
    cost_usd: float = 0.0
    proportion: float = 0.0  # Fraction of total cost (0–1)

    # Metadata
    provider: Optional[str] = None
    model: Optional[str] = None
    latency_ms: Optional[float] = None
    result_bytes: Optional[int] = None


@dataclass
class CostBreakdown:
    """Full cost breakdown for a trace."""

    total_cost_usd: float
    input_tokens: int = 0
    output_tokens: int = 0

    items: list[CostItem] = field(default_factory=list)

    # Summary by category
    mcp_tool_cost: float = 0.0
    llm_cost: float = 0.0
    other_cost: float = 0.0

    # By server
    by_server: dict[str, float] = field(default_factory=dict)
    # By tool
    by_tool: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Compute summaries from items
        for item in self.items:
            if item.source_type == "mcp_tool":
                self.mcp_tool_cost += item.cost_usd
                self.by_tool[item.source] = (
                    self.by_tool.get(item.source, 0.0) + item.cost_usd
                )
            elif item.source_type == "llm":
                self.llm_cost += item.cost_usd
            else:
                self.other_cost += item.cost_usd

            # By server
            if item.source.startswith("MCP:"):
                server = item.source.split(":", 1)[1].rsplit("/", 1)[0]
                self.by_server[server] = (
                    self.by_server.get(server, 0.0) + item.cost_usd
                )


@dataclass
class LLMSpan:
    """Reconstructed LLM call from trace spans."""

    span_id: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float
    start_time: datetime = field(
        default_factory=lambda: datetime.utcnow(),
    )
    start_time: datetime

    # Downstream MCP tool calls that were triggered by this LLM
    triggered_tools: list["MCPToolSpan"] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class MCPToolSpan:
    """Reconstructed MCP tool call from trace spans."""

    span_id: str
    mcp_server: str
    tool_name: str
    result_size_bytes: int
    latency_ms: float
    is_error: bool
    start_time: datetime = field(
        default_factory=lambda: datetime.utcnow(),
    )


def _reconstruct_llm_spans(spans: list[dict[str, Any]]) -> list[LLMSpan]:
    """Extract LLM spans from raw span records.

    Note: In MVP, LLM spans may not be directly captured (they come from
    AgentScope's tracing). Here we return an empty list and the attribution
    engine will work with MCP-only data for now.

    In Phase 2 when AgentScope SDK integration is done, LLM spans will
    be present and used for precise attribution.
    """
    # In the MVP, LLM spans are not captured by the proxy.
    # The attribution engine will return MCP-tool-only costs.
    return []


def _reconstruct_mcp_tool_spans(
    spans: list[dict[str, Any]],
) -> list[MCPToolSpan]:
    """Extract MCP tool call spans from raw span records."""
    result: list[MCPToolSpan] = []

    for span in spans:
        if span.get("span_type") != "mcp.tool.call":
            continue

        start_str = span.get("start_time", "")
        start_time = datetime.utcnow()
        if start_str:
            try:
                start_time = datetime.fromisoformat(
                    start_str.replace("Z", "+00:00"),
                )
            except ValueError:
                pass

        result.append(
            MCPToolSpan(
                span_id=span["id"],
                mcp_server=span.get("mcp_server_name", "unknown"),
                tool_name=span.get("tool_name", "unknown"),
                result_size_bytes=span.get("result_size_bytes", 0) or 0,
                latency_ms=span.get("latency_ms", 0) or 0,
                is_error=bool(span.get("result_is_error")),
                start_time=start_time,
            ),
        )

    return result


def attribute(
    spans: list[dict[str, Any]],
    pricing_func: Any,
) -> CostBreakdown:
    """Attribute token costs to MCP tool calls within a trace.

    This is the main entry point for the attribution engine.
    In MVP mode (no LLM spans), it returns cost based purely on
    MCP tool result sizes as a proxy.

    Args:
        spans: Raw span records from the trace.
        pricing_func: Function(provider, model, input_tokens, output_tokens)
            that returns USD cost. If None, uses default pricing.

    Returns:
        CostBreakdown with attributed costs.
    """
    from .pricing import cost_from_tokens

    if pricing_func is None:
        pricing_func = cost_from_tokens

    llm_spans = _reconstruct_llm_spans(spans)
    mcp_spans = _reconstruct_mcp_tool_spans(spans)

    # Sort by time
    mcp_spans.sort(key=lambda s: s.start_time)
    llm_spans.sort(key=lambda s: s.start_time)

    items: list[CostItem] = []
    total_cost = 0.0

    if llm_spans:
        total_cost = _attribute_with_llm_spans(
            llm_spans, mcp_spans, items, pricing_func
        )
    else:
        # MVP mode: attribute based on result size only
        total_cost = _attribute_mvp(spans, mcp_spans, items)

    # Compute proportions
    if total_cost > 0:
        for item in items:
            item.proportion = item.cost_usd / total_cost

    return CostBreakdown(
        total_cost_usd=total_cost,
        items=items,
    )


def _attribute_with_llm_spans(
    llm_spans: list[LLMSpan],
    mcp_spans: list[MCPToolSpan],
    items: list[CostItem],
    pricing_func: Any,
) -> float:
    """Full attribution when LLM spans are available."""

    total_cost = 0.0

    # Pair each LLM span with the MCP tools it triggered
    for i, llm in enumerate(llm_spans):
        total_cost += llm.cost_usd

        # Add LLM cost item
        items.append(
            CostItem(
                source=f"LLM:{llm.model}",
                source_type="llm",
                input_tokens=llm.input_tokens,
                output_tokens=llm.output_tokens,
                cost_usd=llm.cost_usd,
                provider=llm.provider,
                model=llm.model,
                latency_ms=llm.latency_ms,
            ),
        )

        # Attribute upstream: split LLM's input cost among tools it triggered
        if llm.triggered_tools:
            upstream_cost = llm.cost_usd * 0.5  # Assume 50% of cost is planning
            per_tool = upstream_cost / len(llm.triggered_tools)
            for tool in llm.triggered_tools:
                items.append(
                    CostItem(
                        source=f"MCP:{tool.mcp_server}/{tool.tool_name}",
                        source_type="mcp_tool",
                        cost_usd=per_tool,
                        latency_ms=tool.latency_ms,
                        result_bytes=tool.result_size_bytes,
                    ),
                )

        # Attribute downstream: use result size to split next LLM's cost
        if i + 1 < len(llm_spans):
            next_llm = llm_spans[i + 1]
            total_result_bytes = sum(
                t.result_size_bytes for t in llm.triggered_tools
            )
            if total_result_bytes > 0:
                for tool in llm.triggered_tools:
                    proportion = tool.result_size_bytes / total_result_bytes
                    downstream_cost = next_llm.cost_usd * 0.5 * proportion
                    # Find or create the tool item
                    tool_key = f"MCP:{tool.mcp_server}/{tool.tool_name}"
                    existing = next(
                        (it for it in items if it.source == tool_key),
                        None,
                    )
                    if existing:
                        existing.cost_usd += downstream_cost
                    else:
                        items.append(
                            CostItem(
                                source=tool_key,
                                source_type="mcp_tool",
                                cost_usd=downstream_cost,
                                latency_ms=tool.latency_ms,
                                result_bytes=tool.result_size_bytes,
                            ),
                        )

    return total_cost


def _attribute_mvp(
    spans: list[dict[str, Any]],
    mcp_spans: list[MCPToolSpan],
    items: list[CostItem],
) -> float:
    """MVP attribution: attribute based on result size only.

    In this mode, we don't have LLM token data, so we cannot compute
    real USD costs. Instead, we use result size as a proxy and assign
    a nominal "cost" of $0.001 per 10KB of result data.

    This gives users visibility into which tools generate the most data,
    even without real cost data.
    """
    if not mcp_spans:
        return 0.0

    total_bytes = sum(s.result_size_bytes for s in mcp_spans)

    # Nominal rate: $0.001 per 10KB
    # This gives a relative ranking, not real costs
    RATE_PER_BYTE = 0.001 / (10 * 1024)  # $0.001 / 10KB

    total_cost = 0.0

    for tool in mcp_spans:
        cost = tool.result_size_bytes * RATE_PER_BYTE
        total_cost += cost

        items.append(
            CostItem(
                source=f"MCP:{tool.mcp_server}/{tool.tool_name}",
                source_type="mcp_tool",
                cost_usd=round(cost, 6),
                latency_ms=tool.latency_ms,
                result_bytes=tool.result_size_bytes,
            ),
        )

        # Add error penalty
        if tool.is_error:
            items.append(
                CostItem(
                    source=f"ERROR:{tool.mcp_server}/{tool.tool_name}",
                    source_type="other",
                    cost_usd=0.001,  # Flat error cost
                    result_bytes=0,
                ),
            )

    return round(total_cost, 6)