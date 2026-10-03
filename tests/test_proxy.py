"""Integration tests for the HTTP proxy with a mock MCP backend."""

import json

import httpx
import pytest

from loopprism.proxy.http_handler import MCPHttpHandler
from loopprism.trace.collector import TraceCollector


class TestMCPHttpProxy:
    """Test the proxy handler end-to-end with a mock backend."""

    @pytest.mark.asyncio
    async def test_proxy_tools_call(self, db_path, mock_mcp_backend):
        """Proxy a tools/call request and verify a span is recorded."""
        collector = TraceCollector(db_path)
        await collector.initialize()

        handler = MCPHttpHandler(collector)
        try:
            # Create the proxy handler
            from starlette.requests import Request
            from starlette.testclient import TestClient
            from starlette.applications import Starlette
            from starlette.routing import Route

            # Build a minimal Starlette app with the handler
            async def proxy_endpoint(request: Request):
                return await handler.handle(
                    request=request,
                    server_name="mock",
                    backend_url=mock_mcp_backend,
                )

            app = Starlette(routes=[
                Route("/{path:path}", proxy_endpoint, methods=["POST"]),
            ])
            client = TestClient(app)

            # Send a tools/call request
            response = client.post(
                "/mock",
                json={
                    "jsonrpc": "2.0",
                    "id": "test-1",
                    "method": "tools/call",
                    "params": {
                        "name": "echo",
                        "arguments": {"message": "hello"},
                    },
                },
            )

            assert response.status_code == 200
            body = response.json()
            assert "result" in body
            assert "error" not in body

            # Verify the trace was recorded
            traces = await collector.list_traces(limit=10)
            assert len(traces) >= 1

            trace = traces[0]
            result = await collector.get_trace(trace["id"])
            assert result is not None
            _, spans = result
            assert len(spans) >= 1

            # The span should have the correct tool info
            tool_span = [
                s for s in spans if s["span_type"] == "mcp.tool.call"
            ][0]
            assert tool_span["tool_name"] == "echo"
            assert tool_span["mcp_server_name"] == "mock"
            assert tool_span["status"] == "ok"
            assert tool_span["latency_ms"] is not None

        finally:
            await handler.close()
            await collector.close()

    @pytest.mark.asyncio
    async def test_proxy_tools_list(self, db_path, mock_mcp_backend):
        """Proxy a tools/list request and verify it's traced."""
        collector = TraceCollector(db_path)
        await collector.initialize()

        handler = MCPHttpHandler(collector)
        try:
            from starlette.requests import Request
            from starlette.applications import Starlette
            from starlette.routing import Route
            from starlette.testclient import TestClient

            async def proxy_endpoint(request: Request):
                return await handler.handle(
                    request=request,
                    server_name="mock",
                    backend_url=mock_mcp_backend,
                )

            app = Starlette(routes=[
                Route("/{path:path}", proxy_endpoint, methods=["POST"]),
            ])
            client = TestClient(app)

            response = client.post(
                "/mock",
                json={
                    "jsonrpc": "2.0",
                    "id": "test-2",
                    "method": "tools/list",
                    "params": {},
                },
            )

            assert response.status_code == 200

            # Verify span was recorded with list type
            traces = await collector.list_traces(limit=10)
            assert len(traces) >= 1

        finally:
            await handler.close()
            await collector.close()

    @pytest.mark.asyncio
    async def test_proxy_non_mcp_passthrough(self, db_path, mock_mcp_backend):
        """Non-JSON-RPC requests should pass through without tracing."""
        collector = TraceCollector(db_path)
        await collector.initialize()

        handler = MCPHttpHandler(collector)
        try:
            from starlette.requests import Request
            from starlette.applications import Starlette
            from starlette.routing import Route
            from starlette.testclient import TestClient

            async def proxy_endpoint(request: Request):
                return await handler.handle(
                    request=request,
                    server_name="mock",
                    backend_url=mock_mcp_backend,
                )

            app = Starlette(routes=[
                Route("/{path:path}", proxy_endpoint, methods=["GET", "POST"]),
            ])
            client = TestClient(app)

            # Non-JSON-RPC GET
            response = client.get("/mock/status")
            assert response.status_code == 200

            # No new traces should be created
            traces = await collector.list_traces(limit=10)
            assert len(traces) == 0

        finally:
            await handler.close()
            await collector.close()

    @pytest.mark.asyncio
    async def test_proxy_error_handling(self, db_path):
        """Test handling when backend is unreachable."""
        collector = TraceCollector(db_path)
        await collector.initialize()

        handler = MCPHttpHandler(collector)
        try:
            from starlette.requests import Request
            from starlette.applications import Starlette
            from starlette.routing import Route
            from starlette.testclient import TestClient

            async def proxy_endpoint(request: Request):
                return await handler.handle(
                    request=request,
                    server_name="dead-server",
                    backend_url="http://127.0.0.1:19999",  # Unused port
                )

            app = Starlette(routes=[
                Route("/{path:path}", proxy_endpoint, methods=["POST"]),
            ])
            client = TestClient(app)

            response = client.post(
                "/dead-server",
                json={
                    "jsonrpc": "2.0",
                    "id": "test-err",
                    "method": "tools/call",
                    "params": {"name": "echo", "arguments": {}},
                },
            )

            assert response.status_code == 502
            body = response.json()
            assert "error" in body

        finally:
            await handler.close()
            await collector.close()
