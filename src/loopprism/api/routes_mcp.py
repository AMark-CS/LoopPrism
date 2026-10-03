"""MCP server and tool stats routes."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request

router = APIRouter(tags=["mcp"])


@router.get("/mcp-servers")
async def list_mcp_servers(request: Request):
    """Get stats for all observed MCP servers."""
    collector = request.app.state.collector
    return await collector.get_mcp_server_stats()


@router.get("/mcp-tools")
async def list_mcp_tools(
    request: Request,
    server: Optional[str] = Query(None, description="Filter by MCP server name"),
):
    """Get stats for all observed MCP tools."""
    collector = request.app.state.collector
    return await collector.get_tool_stats(mcp_server=server)
