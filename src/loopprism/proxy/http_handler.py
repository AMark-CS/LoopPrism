"""HTTP handler for MCP proxy interception.

Transparently proxies MCP JSON-RPC traffic, intercepts requests/responses,
extracts tracing metadata, and forwards to the real MCP server.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Optional

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from ..trace.collector import TraceCollector
from ..trace.mcp_semantics import MCPProtocol, ParsedMCPRequest
from ..utils.logging import logger


class MCPHttpHandler:
    """Intercepts MCP HTTP requests, traces them, and forwards to backend."""

    def __init__(
        self,
        collector: TraceCollector,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.collector = collector
        self._client = client
        self._own_client = False

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazily create or return the shared httpx client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(120.0),
                follow_redirects=True,
            )
            self._own_client = True
        return self._client

    async def close(self) -> None:
        """Close the HTTP client if we own it."""
        if self._own_client and self._client:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Main handler entry point
    # ------------------------------------------------------------------

    async def handle(
        self,
        request: Request,
        server_name: str,
        backend_url: str,
    ) -> Response:
        """Handle an incoming proxy request.

        Args:
            request: The Starlette request from the client.
            server_name: The logical MCP server name (from URL path).
            backend_url: The real MCP server URL to forward to.

        Returns:
            The proxied response (JSON-RPC or streaming).
        """
        # Read body
        body_bytes = await request.body()

        # Parse JSON-RPC body
        try:
            body = json.loads(body_bytes) if body_bytes else {}
        except json.JSONDecodeError:
            # Not JSON — just forward without tracing
            return await self._forward(request, backend_url, body_bytes)

        # Parse MCP semantics
        parsed = MCPProtocol.parse(body)

        if not parsed.is_mcp or not parsed.should_trace:
            # Not an MCP call we care about — forward transparently
            return await self._forward(request, backend_url, body_bytes)

        # --- Traceable MCP call ---
        return await self._handle_traced(
            request=request,
            body=body,
            body_bytes=body_bytes,
            parsed=parsed,
            server_name=server_name,
            backend_url=backend_url,
        )

    # ------------------------------------------------------------------
    # Traced handling
    # ------------------------------------------------------------------

    async def _handle_traced(
        self,
        request: Request,
        body: dict,
        body_bytes: bytes,
        parsed: ParsedMCPRequest,
        server_name: str,
        backend_url: str,
    ) -> Response:
        """Handle a traceable MCP request with span creation."""

        # Determine trace ID (from header or new)
        trace_id = request.headers.get("X-LoopPrism-Trace-Id") or request.headers.get("X-Toolglass-Trace-Id") or str(uuid.uuid4())

        # Ensure trace exists
        await self._ensure_trace(trace_id, parsed, server_name)

        # Start span
        span_id = await self.collector.start_span(
            trace_id=trace_id,
            span_type=parsed.span_type or "mcp.generic",
            mcp_server_name=server_name,
            mcp_transport="http",
            mcp_request_method=parsed.method,
            mcp_request_id=str(parsed.request_id) if parsed.request_id else None,
            tool_name=parsed.tool_name,
            tool_arguments=parsed.tool_arguments,
            tool_call_id=parsed.tool_call_id,
            attributes={
                "backend_url": backend_url,
                "user_agent": request.headers.get("user-agent", ""),
            },
        )

        # Forward and measure
        start = time.monotonic()
        try:
            response = await self._forward(request, backend_url, body_bytes)
        except Exception as exc:
            latency = (time.monotonic() - start) * 1000
            await self.collector.finish_span(
                span_id=span_id,
                latency_ms=latency,
                result_is_error=True,
                status="error",
                attributes={"error": str(exc)},
            )
            await self.collector.finalize_trace(trace_id)
            raise

        latency = (time.monotonic() - start) * 1000

        # Extract response body for tracing
        response_body_bytes = b""
        result_is_error = False

        if hasattr(response, "body"):
            # Standard JSONResponse
            response_body_bytes = response.body
        else:
            # For StreamingResponse, try to read
            pass

        # Parse response for metadata
        try:
            response_body = json.loads(response_body_bytes) if response_body_bytes else {}
            response_meta = MCPProtocol.parse_response(
                response_body,
                parsed.span_type,
            )
            result_is_error = response_meta.pop("result_is_error", False)
        except json.JSONDecodeError:
            response_meta = {}

        # Finish span
        await self.collector.finish_span(
            span_id=span_id,
            latency_ms=latency,
            result_content=(
                json.loads(response_body_bytes) if response_body_bytes else None
            ),
            result_size_bytes=len(response_body_bytes) if response_body_bytes else 0,
            result_is_error=result_is_error,
            status="error" if result_is_error else "ok",
            attributes=response_meta,
        )

        # Finalize trace
        await self.collector.finalize_trace(trace_id)

        # Inject trace ID into response header
        if isinstance(response, JSONResponse):
            response.headers["X-LoopPrism-Trace-Id"] = trace_id
        else:
            response.headers["X-LoopPrism-Trace-Id"] = trace_id

        return response

    # ------------------------------------------------------------------
    # Forwarding
    # ------------------------------------------------------------------

    async def _forward(
        self,
        request: Request,
        backend_url: str,
        body_bytes: bytes,
    ) -> Response:
        """Forward a request to the backend MCP server.

        Copies method, headers (except host), and body.
        Returns a JSONResponse or StreamingResponse.
        """
        client = await self._get_client()

        # Build forwarded URL
        path = request.url.path
        # Remove the server_name prefix if present
        # e.g., /github/mcp → /mcp
        # The backend_url should already include any path prefix
        url = backend_url.rstrip("/") + "/" + path.lstrip("/")

        # Forward headers (exclude host, transfer-encoding)
        headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower()
            not in ("host", "transfer-encoding", "content-length")
        }

        try:
            backend_resp = await client.request(
                method=request.method,
                url=url,
                headers=headers,
                content=body_bytes or None,
            )
        except httpx.RequestError as exc:
            logger.error("Backend request failed: %s → %s: %s", request.method, url, exc)
            return JSONResponse(
                content={
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -32603,
                        "message": f"Backend unreachable: {exc}",
                    },
                    "id": None,
                },
                status_code=502,
            )

        # Build response
        response_headers = {
            k: v
            for k, v in backend_resp.headers.items()
            if k.lower() not in ("transfer-encoding", "content-encoding")
        }

        content_type = backend_resp.headers.get(
            "content-type",
            "application/json",
        )

        return Response(
            content=backend_resp.content,
            status_code=backend_resp.status_code,
            headers=response_headers,
            media_type=content_type,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _ensure_trace(
        self,
        trace_id: str,
        parsed: ParsedMCPRequest,
        server_name: str,
    ) -> None:
        """Ensure a trace record exists (idempotent)."""
        # Try to create — ignore if already exists
        try:
            await self.collector.create_trace(
                trace_id=trace_id,
                root_span_type=(
                    parsed.span_type.value
                    if parsed.span_type
                    else None
                ),
                root_span_name=(
                    parsed.tool_name or parsed.method or "mcp_call"
                ),
            )
        except Exception:
            # Trace likely already exists — that's fine
            pass
