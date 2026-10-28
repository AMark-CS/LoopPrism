"""FastAPI application for the loopprism dashboard API."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..trace.collector import TraceCollector
from ..trace.ingest import AgentIngestor
from .routes_cost import router as cost_router
from .routes_ingest import router as ingest_router
from .routes_mcp import router as mcp_router
from .routes_sessions import router as sessions_router
from .routes_traces import router as traces_router


def create_app(
    collector: TraceCollector,
    dashboard_enabled: bool = True,
) -> FastAPI:
    """Create the FastAPI application.

    Args:
        collector: TraceCollector instance for data access.
        dashboard_enabled: Whether to serve the built-in dashboard.

    Returns:
        Configured FastAPI application.
    """
    app = FastAPI(
        title="LoopPrism",
        description="Looking glass for your AI tools — API",
        version=__version__,
    )

    # CORS
    # Only pages served from this machine may call the API from a browser;
    # session content must not be readable by arbitrary websites.
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$",
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Inject collector into app state
    app.state.collector = collector
    app.state.ingestor = AgentIngestor(collector)

    # Register API routers
    app.include_router(traces_router, prefix="/api")
    app.include_router(mcp_router, prefix="/api")
    app.include_router(cost_router, prefix="/api")
    app.include_router(sessions_router, prefix="/api")
    app.include_router(ingest_router, prefix="/api")

    # Health check
    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    # Serve dashboard static files (if built)
    if dashboard_enabled:
        dashboard_dist = (
            Path(__file__).parent.parent / "dashboard" / "dist"
        )
        if dashboard_dist.exists():
            app.mount(
                "/",
                StaticFiles(directory=str(dashboard_dist), html=True),
                name="dashboard",
            )

    return app
