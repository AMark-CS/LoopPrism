"""MCP interception proxy server.

Provides an async context manager that runs the transparent MCP proxy.
The proxy intercepts all incoming HTTP requests, traces MCP calls,
and forwards traffic to the appropriate backend MCP servers.

Backend routing is done by URL path prefix:
    /github/*  → forwards to the GitHub MCP server
    /slack/*   → forwards to the Slack MCP server
    etc.

Backend mappings are configured via the proxy config or dynamically.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional

import httpx
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..trace.collector import TraceCollector
from ..utils.logging import logger
from .http_handler import MCPHttpHandler


class ProxyServer:
    """Transparent MCP proxy with built-in tracing.

    Usage:
        collector = TraceCollector("traces.db")
        await collector.initialize()

        proxy = ProxyServer(host="127.0.0.1", port=4317, collector=collector)
        async with proxy:
            await proxy.serve()
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 4317,
        collector: Optional[TraceCollector] = None,
        backend_map: Optional[dict[str, str]] = None,
    ) -> None:
        """
        Args:
            host: Bind address.
            port: Listen port.
            collector: TraceCollector instance for recording spans.
            backend_map: Mapping of URL prefix → backend URL.
                e.g. {"github": "https://api.github.com/mcp"}
        """
        self.host = host
        self.port = port
        self.collector = collector
        self.backend_map: dict[str, str] = backend_map or {}

        self._handler: Optional[MCPHttpHandler] = None
        self._app: Optional[Starlette] = None
        self._client: Optional[httpx.AsyncClient] = None

    # ------------------------------------------------------------------
    # Server lifecycle
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "ProxyServer":
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(120.0),
            follow_redirects=True,
        )
        if self.collector is None:
            raise RuntimeError("collector is required")
        self._handler = MCPHttpHandler(
            collector=self.collector,
            client=self._client,
        )
        self._app = self._build_app()
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._handler:
            await self._handler.close()
        if self._client:
            await self._client.aclose()

    async def serve(self) -> None:
        """Start serving proxy traffic (blocking)."""
        import uvicorn

        if self._app is None:
            raise RuntimeError("ProxyServer not initialized — use async with")

        config = uvicorn.Config(
            self._app,
            host=self.host,
            port=self.port,
            log_level="info",
        )
        server = uvicorn.Server(config)
        await server.serve()

    # ------------------------------------------------------------------
    # App construction
    # ------------------------------------------------------------------

    def _build_app(self) -> Starlette:
        """Build the Starlette proxy application."""
        routes = [
            Route(
                "/health",
                self._health_endpoint,
                methods=["GET"],
            ),
            Route(
                "/__backends",
                self._list_backends,
                methods=["GET"],
            ),
            # Catch-all route for proxying
            Route(
                "/{path:path}",
                self._proxy_endpoint,
                methods=[
                    "GET",
                    "POST",
                    "PUT",
                    "DELETE",
                    "PATCH",
                    "OPTIONS",
                ],
            ),
        ]

        app = Starlette(routes=routes)

        # Add CORS middleware for dashboard
        app.add_middleware(
            BaseHTTPMiddleware,
            dispatch=self._cors_middleware,
        )

        return app

    # ------------------------------------------------------------------
    # Endpoints
    # ------------------------------------------------------------------

    async def _health_endpoint(self, request: Request) -> JSONResponse:
        return JSONResponse({
            "status": "ok",
            "backends": list(self.backend_map.keys()),
        })

    async def _list_backends(self, request: Request) -> JSONResponse:
        return JSONResponse({"backends": self.backend_map})

    async def _proxy_endpoint(self, request: Request) -> Response:
        """Main proxy endpoint — routes to backend based on URL path."""
        assert self._handler is not None

        path = request.url.path.strip("/")

        if not path:
            return JSONResponse(
                {
                    "loopprism": "proxy",
                    "message": "No MCP server specified in path",
                    "example": f"http://localhost:{self.port}/<server-name>",
                },
                status_code=400,
            )

        # Extract server name from first path segment
        parts = path.split("/", 1)
        server_name = parts[0]

        # Resolve backend URL
        backend_url = self.backend_map.get(server_name)
        if backend_url is None:
            # If no explicit mapping, try to construct from request
            # (useful for dynamic backends)
            backend_url = self._resolve_backend(server_name, request)

        if backend_url is None:
            return JSONResponse(
                {
                    "error": f"Unknown MCP server: {server_name}",
                    "registered": list(self.backend_map.keys()),
                    "hint": "Add backend via proxy config or URL query param",
                },
                status_code=404,
            )

        # Delegate to handler
        return await self._handler.handle(
            request=request,
            server_name=server_name,
            backend_url=backend_url,
        )

    # ------------------------------------------------------------------
    # Backend resolution
    # ------------------------------------------------------------------

    def _resolve_backend(
        self,
        server_name: str,
        request: Request,
    ) -> Optional[str]:
        """Try to resolve a backend URL from various sources.

        Priority:
        1. Explicit backend_map entry
        2. ?backend= query parameter
        3. X-LoopPrism-Backend header
        """
        # Query parameter
        backend = request.query_params.get("backend")
        if backend:
            self.backend_map[server_name] = backend
            return backend

        # Header
        backend = request.headers.get("X-LoopPrism-Backend") or request.headers.get("X-Toolglass-Backend")
        if backend:
            self.backend_map[server_name] = backend
            return backend

        return None

    # ------------------------------------------------------------------
    # Middleware
    # ------------------------------------------------------------------

    async def _cors_middleware(
        self,
        request: Request,
        call_next,
    ) -> Response:
        """Add CORS headers for dashboard access."""
        response = await call_next(request)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "*"
        return response

    # ------------------------------------------------------------------
    # Backend management
    # ------------------------------------------------------------------

    def add_backend(self, name: str, url: str) -> None:
        """Register a backend MCP server."""
        self.backend_map[name] = url

    def remove_backend(self, name: str) -> None:
        """Unregister a backend MCP server."""
        self.backend_map.pop(name, None)
