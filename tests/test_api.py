"""Tests for the FastAPI REST API."""

import pytest
from httpx import ASGITransport, AsyncClient

from loopprism.api.app import create_app


@pytest.fixture
async def api_client(collector):
    """Create an async test client for the FastAPI app."""
    app = create_app(collector=collector, dashboard_enabled=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        yield client


class TestAPI:
    @pytest.mark.asyncio
    async def test_health(self, api_client):
        resp = await api_client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_list_traces_empty(self, api_client):
        resp = await api_client.get("/api/traces")
        assert resp.status_code == 200
        data = resp.json()
        assert data["traces"] == []

    @pytest.mark.asyncio
    async def test_create_and_get_trace(self, api_client, collector):
        # Create a trace with spans via collector
        trace_id = await collector.create_trace()
        sid = await collector.start_span(
            trace_id=trace_id,
            span_type="mcp.tool.call",
            mcp_server_name="test",
            tool_name="echo",
        )
        await collector.finish_span(
            span_id=sid,
            latency_ms=10.0,
            result_size_bytes=100,
        )
        await collector.finalize_trace(trace_id)

        # Get via API
        resp = await api_client.get(f"/api/traces/{trace_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["trace"]["id"] == trace_id
        assert len(data["spans"]) == 1
        assert data["spans"][0]["tool_name"] == "echo"

    @pytest.mark.asyncio
    async def test_get_trace_not_found(self, api_client):
        resp = await api_client.get("/api/traces/nonexistent")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_mcp_servers_stats(self, api_client, collector):
        trace_id = await collector.create_trace()
        sid = await collector.start_span(
            trace_id=trace_id,
            span_type="mcp.tool.call",
            mcp_server_name="github",
            tool_name="search",
        )
        await collector.finish_span(
            span_id=sid,
            latency_ms=50.0,
            result_size_bytes=1000,
        )

        resp = await api_client.get("/api/mcp-servers")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["mcp_server_name"] == "github"
        assert data[0]["call_count"] == 1

    @pytest.mark.asyncio
    async def test_mcp_tools_stats(self, api_client, collector):
        trace_id = await collector.create_trace()
        sid = await collector.start_span(
            trace_id=trace_id,
            span_type="mcp.tool.call",
            mcp_server_name="github",
            tool_name="search",
        )
        await collector.finish_span(
            span_id=sid,
            latency_ms=50.0,
            result_size_bytes=1000,
        )

        resp = await api_client.get("/api/mcp-tools")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["tool_name"] == "search"

    @pytest.mark.asyncio
    async def test_cost_summary(self, api_client, collector):
        trace_id = await collector.create_trace()
        sid = await collector.start_span(
            trace_id=trace_id,
            span_type="mcp.tool.call",
            mcp_server_name="github",
            tool_name="search",
        )
        await collector.finish_span(
            span_id=sid,
            latency_ms=50.0,
            result_size_bytes=1000,
        )

        resp = await api_client.get("/api/cost/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_tool_calls"] == 1
        assert data["total_result_bytes"] == 1000

    @pytest.mark.asyncio
    async def test_delete_traces(self, api_client, collector):
        trace_id = await collector.create_trace()
        await collector.start_span(
            trace_id=trace_id,
            span_type="mcp.tool.call",
            mcp_server_name="test",
            tool_name="echo",
        )

        resp = await api_client.delete("/api/traces")
        assert resp.status_code == 200

        traces = await collector.list_traces(limit=10)
        assert len(traces) == 0
