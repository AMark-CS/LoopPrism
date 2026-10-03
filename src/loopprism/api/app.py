"""FastAPI application for the loopprism dashboard API."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from ..trace.collector import TraceCollector
from .routes_cost import router as cost_router
from .routes_mcp import router as mcp_router
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
        version="0.1.0",
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Inject collector into app state
    app.state.collector = collector

    # Register API routers
    app.include_router(traces_router, prefix="/api")
    app.include_router(mcp_router, prefix="/api")
    app.include_router(cost_router, prefix="/api")

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
