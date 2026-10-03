"""Tests for cost attribution engine."""

import pytest

from loopprism.cost.attribution import (
    CostBreakdown,
    CostItem,
    MCPToolSpan,
    _attribute_mvp,
    _reconstruct_mcp_tool_spans,
    attribute,
)
from loopprism.cost.pricing import (
    ModelPricing,
    cost_from_tokens,
    get_pricing,
)


class TestPricing:
    def test_model_pricing_cost(self):
        """Test cost calculation from token counts."""
        p = ModelPricing(input_cost_per_m=15.0, output_cost_per_m=75.0)

        # 1M input + 1M output
        cost = p.cost(input_tokens=1_000_000, output_tokens=1_000_000)
        assert cost == 90.0  # $15 + $75

        # 0 tokens
        assert p.cost(0, 0) == 0.0

        # Small count
        cost = p.cost(input_tokens=1000, output_tokens=500)
        assert cost == pytest.approx(0.0525, rel=1e-6)

    def test_get_pricing_anthropic(self):
        """Test Anthropic pricing lookup."""
        p = get_pricing("anthropic", "claude-opus-4-8")
        assert p is not None
        assert p.input_cost_per_m == 15.0

    def test_get_pricing_partial_match(self):
        """Test partial model name matching."""
        p = get_pricing("anthropic", "claude-opus")
        assert p is not None

    def test_get_pricing_unknown(self):
        """Test unknown model returns None."""
        p = get_pricing("unknown", "unknown")
        assert p is None

    def test_cost_from_tokens(self):
        """Test full cost-from-tokens flow."""
        cost = cost_from_tokens(
            "anthropic",
            "claude-opus-4-8",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        assert cost == 90.0

    def test_cost_from_tokens_ollama_free(self):
        """Test local models are priced at $0."""
        cost = cost_from_tokens(
            "ollama",
            "llama3",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        assert cost == 0.0


class TestReconstructMCPSpans:
    def test_reconstruct_single_span(self):
        """Test reconstructing a single MCP tool span."""
        raw_spans = [
            {
                "id": "span-1",
                "span_type": "mcp.tool.call",
                "mcp_server_name": "github",
                "tool_name": "search",
                "result_size_bytes": 5000,
                "latency_ms": 120.5,
                "result_is_error": 0,
                "start_time": "2026-06-15T10:00:00",
            }
        ]

        spans = _reconstruct_mcp_tool_spans(raw_spans)

        assert len(spans) == 1
        assert spans[0].mcp_server == "github"
        assert spans[0].tool_name == "search"
        assert spans[0].result_size_bytes == 5000
        assert spans[0].latency_ms == 120.5
        assert spans[0].is_error is False

    def test_reconstruct_filters_non_tool_spans(self):
        """Test that only mcp.tool.call spans are reconstructed."""
        raw_spans = [
            {
                "id": "span-1",
                "span_type": "mcp.tool.call",
                "mcp_server_name": "github",
                "tool_name": "search",
                "result_size_bytes": 5000,
                "latency_ms": 100.0,
                "result_is_error": 0,
                "start_time": "2026-06-15T10:00:00",
            },
            {
                "id": "span-2",
                "span_type": "mcp.server.list_tools",
                "mcp_server_name": "github",
                "tool_name": None,
                "result_size_bytes": 1000,
                "latency_ms": 10.0,
                "result_is_error": 0,
                "start_time": "2026-06-15T10:00:00",
            },
        ]

        spans = _reconstruct_mcp_tool_spans(raw_spans)

        # Only tool.call spans are included
        assert len(spans) == 1
        assert spans[0].tool_name == "search"


class TestMVPAttribution:
    """Test MVP attribution (no LLM spans available)."""

    def test_mvp_no_spans(self):
        """Test attribution with no spans."""
        items: list = []
        cost = _attribute_mvp([], [], items)
        assert cost == 0.0
        assert items == []

    def test_mvp_single_tool(self):
        """Test attribution with a single tool."""
        spans = [
            MCPToolSpan(
                span_id="s1",
                mcp_server="github",
                tool_name="search",
                result_size_bytes=10 * 1024,  # 10KB
                latency_ms=100.0,
                is_error=False,
            )
        ]

        items: list[CostItem] = []
        cost = _attribute_mvp([], spans, items)

        # 10KB at $0.001 / 10KB = $0.001
        assert cost == pytest.approx(0.001, rel=1e-6)
        assert len(items) == 1
        assert items[0].source == "MCP:github/search"
        assert items[0].cost_usd == pytest.approx(0.001, rel=1e-6)
        assert items[0].result_bytes == 10 * 1024

    def test_mvp_result_size_proportional(self):
        """Test that cost is proportional to result size."""
        # Small result: 1KB
        small = MCPToolSpan(
            span_id="s1",
            mcp_server="db",
            tool_name="query",
            result_size_bytes=1024,
            latency_ms=50.0,
            is_error=False,
        )
        # Large result: 9KB (9x larger)
        large = MCPToolSpan(
            span_id="s2",
            mcp_server="db",
            tool_name="full_scan",
            result_size_bytes=9 * 1024,
            latency_ms=500.0,
            is_error=False,
        )

        items: list[CostItem] = []
        cost = _attribute_mvp([], [small, large], items)

        # 10KB total, rate = $0.001 / 10KB = $0.0000001/byte
        # small: 1KB = $0.0001, large: 9KB = $0.0009
        small_item = next(i for i in items if i.source == "MCP:db/query")
        large_item = next(i for i in items if i.source == "MCP:db/full_scan")

        assert small_item.cost_usd < large_item.cost_usd
        assert large_item.cost_usd == pytest.approx(
            9 * small_item.cost_usd, rel=1e-6
        )

    def test_mvp_error_penalty(self):
        """Test that errors add a flat penalty."""
        error_span = MCPToolSpan(
            span_id="s1",
            mcp_server="slack",
            tool_name="send",
            result_size_bytes=0,
            latency_ms=1000.0,
            is_error=True,
        )

        items: list[CostItem] = []
        cost = _attribute_mvp([], [error_span], items)

        # Should have 2 items: the tool (free, no bytes) + error penalty
        assert len(items) == 2
        error_items = [i for i in items if i.source_type == "other"]
        assert len(error_items) == 1
        assert error_items[0].cost_usd == 0.001


class TestAttribute:
    """Test the main attribute() function."""

    def test_attribute_with_no_spans(self):
        """Test attribution with empty span list."""
        breakdown = attribute([], pricing_func=None)

        assert breakdown.total_cost_usd == 0.0
        assert breakdown.items == []
        assert breakdown.mcp_tool_cost == 0.0

    def test_attribute_creates_breakdown(self):
        """Test that attribute() returns a properly structured CostBreakdown."""
        raw_spans = [
            {
                "id": "span-1",
                "span_type": "mcp.tool.call",
                "mcp_server_name": "github",
                "tool_name": "search",
                "result_size_bytes": 10240,  # 10KB
                "latency_ms": 100.0,
                "result_is_error": 0,
                "start_time": "2026-06-15T10:00:00",
            }
        ]

        breakdown = attribute(raw_spans, pricing_func=None)

        assert breakdown.total_cost_usd > 0
        assert len(breakdown.items) >= 1
        assert breakdown.mcp_tool_cost == breakdown.total_cost_usd

        # Check by_tool is populated
        assert "MCP:github/search" in breakdown.by_tool

    def test_attribute_proportions_sum_to_one(self):
        """Test that item proportions sum to approximately 1.0."""
        raw_spans = [
            {
                "id": f"span-{i}",
                "span_type": "mcp.tool.call",
                "mcp_server_name": "test",
                "tool_name": f"tool_{i}",
                "result_size_bytes": 1000 * (i + 1),
                "latency_ms": 100.0,
                "result_is_error": 0,
                "start_time": "2026-06-15T10:00:00",
            }
            for i in range(5)
        ]

        breakdown = attribute(raw_spans, pricing_func=None)

        if breakdown.total_cost_usd > 0:
            total_proportion = sum(item.proportion for item in breakdown.items)
            # Proportions sum to 1.0 (excluding error penalties)
            mcp_items = [i for i in breakdown.items if i.source_type == "mcp_tool"]
            if mcp_items:
                assert sum(i.proportion for i in mcp_items) == pytest.approx(
                    1.0, abs=0.01
                )
