"""Unit tests for TraceCollector."""

import pytest


class TestTraceCollector:
    """Test trace and span lifecycle in SQLite."""

    @pytest.mark.asyncio
    async def test_create_and_get_trace(self, collector):
        """Create a trace and retrieve it."""
        trace_id = await collector.create_trace(
            conversation_id="conv-1",
            root_span_type="mcp.tool.call",
            root_span_name="search",
        )

        result = await collector.get_trace(trace_id)
        assert result is not None

        trace, spans = result
        assert trace["id"] == trace_id
        assert trace["conversation_id"] == "conv-1"
        assert trace["span_count"] == 0
        assert spans == []

    @pytest.mark.asyncio
    async def test_start_and_finish_span(self, collector):
        """Start a span, finish it, and verify it's stored."""
        trace_id = await collector.create_trace()

        span_id = await collector.start_span(
            trace_id=trace_id,
            span_type="mcp.tool.call",
            mcp_server_name="test-server",
            mcp_request_method="tools/call",
            tool_name="echo",
            tool_arguments={"message": "hello"},
        )

        await collector.finish_span(
            span_id=span_id,
            latency_ms=42.5,
            result_size_bytes=100,
            result_is_error=False,
        )

        await collector.finalize_trace(trace_id)

        _, spans = await collector.get_trace(trace_id)
        assert len(spans) == 1

        span = spans[0]
        assert span["span_type"] == "mcp.tool.call"
        assert span["mcp_server_name"] == "test-server"
        assert span["tool_name"] == "echo"
        assert span["latency_ms"] == 42.5
        assert span["result_size_bytes"] == 100
        assert span["result_is_error"] == 0
        assert span["status"] == "ok"

    @pytest.mark.asyncio
    async def test_error_span(self, collector):
        """Test span that records an error."""
        trace_id = await collector.create_trace()

        span_id = await collector.start_span(
            trace_id=trace_id,
            span_type="mcp.tool.call",
            mcp_server_name="bad-server",
            tool_name="crash",
        )

        await collector.finish_span(
            span_id=span_id,
            latency_ms=100.0,
            result_is_error=True,
            status="error",
        )

        await collector.finalize_trace(trace_id)

        _, spans = await collector.get_trace(trace_id)
        span = spans[0]
        assert span["result_is_error"] == 1
        assert span["status"] == "error"

    @pytest.mark.asyncio
    async def test_list_traces(self, collector):
        """Test listing traces with filters."""
        # Create a few traces
        t1 = await collector.create_trace()
        await collector.start_span(
            trace_id=t1,
            span_type="mcp.tool.call",
            mcp_server_name="github",
            tool_name="search",
        )
        await collector.finalize_trace(t1)

        t2 = await collector.create_trace()
        await collector.start_span(
            trace_id=t2,
            span_type="mcp.tool.call",
            mcp_server_name="slack",
            tool_name="send_message",
        )
        await collector.finalize_trace(t2)

        # List all
        traces = await collector.list_traces(limit=10)
        assert len(traces) == 2

        # Filter by server
        traces = await collector.list_traces(
            limit=10,
            mcp_server="github",
        )
        assert len(traces) == 1

    @pytest.mark.asyncio
    async def test_mcp_server_stats(self, collector):
        """Test MCP server stats aggregation."""
        trace_id = await collector.create_trace()

        # Add two spans from different servers
        for server, tool, latency, size, is_error in [
            ("github", "search", 50.0, 1000, False),
            ("github", "read_file", 100.0, 5000, False),
            ("slack", "send_message", 200.0, 200, True),
        ]:
            sid = await collector.start_span(
                trace_id=trace_id,
                span_type="mcp.tool.call",
                mcp_server_name=server,
                tool_name=tool,
            )
            await collector.finish_span(
                span_id=sid,
                latency_ms=latency,
                result_size_bytes=size,
                result_is_error=is_error,
            )

        await collector.finalize_trace(trace_id)

        stats = await collector.get_mcp_server_stats()

        # github should have 2 calls, slack 1
        github = next(
            s for s in stats if s["mcp_server_name"] == "github"
        )
        slack = next(
            s for s in stats if s["mcp_server_name"] == "slack"
        )

        assert github["call_count"] == 2
        assert github["avg_latency_ms"] == 75.0  # (50+100)/2
        assert github["error_count"] == 0

        assert slack["call_count"] == 1
        assert slack["error_count"] == 1

    @pytest.mark.asyncio
    async def test_cleanup_old_traces(self, collector):
        """Test that old traces are deleted."""
        trace_id = await collector.create_trace()
        await collector.start_span(
            trace_id=trace_id,
            span_type="mcp.tool.call",
            mcp_server_name="test",
            tool_name="echo",
        )

        # Delete with 0 days retention (deletes all)
        deleted = await collector.cleanup_old_traces(retention_days=0)
        assert deleted == 1

        result = await collector.get_trace(trace_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_tool_stats(self, collector):
        """Test tool stats aggregation."""
        trace_id = await collector.create_trace()

        for tool_name, latency in [("echo", 10.0), ("echo", 20.0), ("search", 50.0)]:
            sid = await collector.start_span(
                trace_id=trace_id,
                span_type="mcp.tool.call",
                mcp_server_name="test",
                tool_name=tool_name,
            )
            await collector.finish_span(
                span_id=sid,
                latency_ms=latency,
                result_size_bytes=100,
            )

        stats = await collector.get_tool_stats()

        echo = next(s for s in stats if s["tool_name"] == "echo")
        search = next(s for s in stats if s["tool_name"] == "search")

        assert echo["call_count"] == 2
        assert echo["avg_latency_ms"] == 15.0
        assert search["call_count"] == 1
        assert search["avg_latency_ms"] == 50.0

    @pytest.mark.asyncio
    async def test_finalize_trace_computes_stats(self, collector):
        """Test that finalize_trace correctly computes summary stats."""
        trace_id = await collector.create_trace()

        sid = await collector.start_span(
            trace_id=trace_id,
            span_type="mcp.tool.call",
            mcp_server_name="github",
            tool_name="search",
        )
        await collector.finish_span(
            span_id=sid,
            latency_ms=100.0,
            result_size_bytes=500,
        )

        await collector.finalize_trace(trace_id)

        trace, _ = await collector.get_trace(trace_id)
        assert trace["span_count"] == 1
        assert trace["error_count"] == 0
        assert trace["mcp_servers"] == '["github"]'


class TestRunDataModel:
    """Run/span data model: seq ordering, attribute merge, migration."""

    @pytest.mark.asyncio
    async def test_seq_is_per_run_and_orders_spans(self, collector):
        a = await collector.create_trace()
        b = await collector.create_trace()
        ids_a = [
            await collector.start_span(trace_id=a, span_type="mcp.tool.call")
            for _ in range(3)
        ]
        await collector.start_span(trace_id=b, span_type="mcp.tool.call")

        _, spans = await collector.get_trace(a)
        assert [s["id"] for s in spans] == ids_a
        assert [s["seq"] for s in spans] == [1, 2, 3]
        assert all(s["kind"] == "mcp.tool.call" for s in spans)

        _, spans_b = await collector.get_trace(b)
        assert [s["seq"] for s in spans_b] == [1]

    @pytest.mark.asyncio
    async def test_finish_span_merges_attributes_into_valid_json(self, collector):
        import json

        tid = await collector.create_trace()
        sid = await collector.start_span(
            trace_id=tid,
            span_type="mcp.tool.call",
            attributes={"backend_url": "http://x"},
        )
        await collector.finish_span(
            span_id=sid, latency_ms=1.0, attributes={"error": "boom"}
        )
        _, spans = await collector.get_trace(tid)
        assert json.loads(spans[0]["attributes_json"]) == {
            "backend_url": "http://x",
            "error": "boom",
        }

    @pytest.mark.asyncio
    async def test_finish_span_without_start_attributes(self, collector):
        import json

        tid = await collector.create_trace()
        sid = await collector.start_span(trace_id=tid, span_type="mcp.tool.call")
        await collector.finish_span(span_id=sid, latency_ms=1.0)
        _, spans = await collector.get_trace(tid)
        assert json.loads(spans[0]["attributes_json"]) == {}

    @pytest.mark.asyncio
    async def test_session_id_and_conversation_id_alias(self, collector):
        t1 = await collector.create_trace(
            session_id="s1", correlation_source="explicit"
        )
        t2 = await collector.create_trace(conversation_id="legacy")
        trace1, _ = await collector.get_trace(t1)
        trace2, _ = await collector.get_trace(t2)
        assert trace1["session_id"] == trace1["conversation_id"] == "s1"
        assert trace1["correlation_source"] == "explicit"
        assert trace1["status"] == "running"
        assert trace2["session_id"] == "legacy"

    @pytest.mark.asyncio
    async def test_migrates_legacy_database(self, db_path):
        import sqlite3

        from loopprism.trace.collector import TraceCollector

        conn = sqlite3.connect(db_path)
        conn.executescript(
            """
            CREATE TABLE traces (id TEXT PRIMARY KEY, conversation_id TEXT,
                timestamp DATETIME DEFAULT (datetime('now')), root_span_type TEXT,
                root_span_name TEXT, total_latency_ms REAL, total_cost_usd REAL,
                span_count INTEGER DEFAULT 0, error_count INTEGER DEFAULT 0,
                mcp_servers TEXT, tags TEXT, metadata TEXT);
            CREATE TABLE spans (id TEXT PRIMARY KEY, trace_id TEXT NOT NULL,
                parent_span_id TEXT, span_type TEXT DEFAULT 'generic',
                start_time DATETIME DEFAULT (datetime('now')), end_time DATETIME,
                latency_ms REAL, mcp_server_name TEXT, mcp_server_version TEXT,
                mcp_transport TEXT, mcp_request_method TEXT, mcp_request_id TEXT,
                tool_name TEXT, tool_arguments TEXT, tool_call_id TEXT,
                result_content_preview TEXT, result_size_bytes INTEGER,
                result_is_error INTEGER DEFAULT 0, upstream_llm_tokens INTEGER,
                downstream_llm_tokens INTEGER, attributes_json TEXT,
                status TEXT DEFAULT 'ok');
            INSERT INTO traces (id, conversation_id) VALUES ('old', 'c');
            """
        )
        conn.commit()
        conn.close()

        c = TraceCollector(db_path)
        await c.initialize()
        await c.close()
        await c.initialize()  # reopening an already-migrated db must be a no-op
        try:
            trace, _ = await c.get_trace("old")
            assert trace["conversation_id"] == "c"
            sid = await c.start_span(trace_id="old", span_type="mcp.tool.call")
            _, spans = await c.get_trace("old")
            assert spans[0]["id"] == sid and spans[0]["seq"] == 1
        finally:
            await c.close()
