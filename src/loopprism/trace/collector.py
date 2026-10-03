"""Trace collector — writes spans and traces to SQLite.

The collector is the central write path for all trace data.
It provides async methods to start and finish spans, and query traces.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

import aiosqlite

from ..utils.logging import logger
from .models import Span as SpanModel
from .models import Trace as TraceModel
from .mcp_semantics import MCPSpanType


class TraceCollector:
    """Async trace data collector backed by SQLite."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Open database and create schema if needed."""
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._create_tables()
        logger.info("TraceCollector initialized: %s", self.db_path)

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def _create_tables(self) -> None:
        """Create the traces and spans tables."""
        assert self._conn is not None
        await self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS traces (
                id TEXT PRIMARY KEY,
                conversation_id TEXT,
                timestamp DATETIME DEFAULT (datetime('now')),
                root_span_type TEXT,
                root_span_name TEXT,
                total_latency_ms REAL,
                total_cost_usd REAL,
                span_count INTEGER DEFAULT 0,
                error_count INTEGER DEFAULT 0,
                mcp_servers TEXT,
                tags TEXT,
                metadata TEXT
            );

            CREATE TABLE IF NOT EXISTS spans (
                id TEXT PRIMARY KEY,
                trace_id TEXT NOT NULL REFERENCES traces(id) ON DELETE CASCADE,
                parent_span_id TEXT,
                span_type TEXT DEFAULT 'generic',
                start_time DATETIME DEFAULT (datetime('now')),
                end_time DATETIME,
                latency_ms REAL,
                mcp_server_name TEXT,
                mcp_server_version TEXT,
                mcp_transport TEXT,
                mcp_request_method TEXT,
                mcp_request_id TEXT,
                tool_name TEXT,
                tool_arguments TEXT,
                tool_call_id TEXT,
                result_content_preview TEXT,
                result_size_bytes INTEGER,
                result_is_error INTEGER DEFAULT 0,
                upstream_llm_tokens INTEGER,
                downstream_llm_tokens INTEGER,
                attributes_json TEXT,
                status TEXT DEFAULT 'ok'
            );

            CREATE INDEX IF NOT EXISTS idx_spans_trace_id
                ON spans(trace_id);
            CREATE INDEX IF NOT EXISTS idx_spans_tool_name
                ON spans(tool_name);
            CREATE INDEX IF NOT EXISTS idx_spans_mcp_server
                ON spans(mcp_server_name);
            CREATE INDEX IF NOT EXISTS idx_spans_timestamp
                ON spans(start_time);
            CREATE INDEX IF NOT EXISTS idx_traces_timestamp
                ON traces(timestamp);
        """)
        await self._conn.commit()

    # ------------------------------------------------------------------
    # Trace management
    # ------------------------------------------------------------------

    async def create_trace(
        self,
        trace_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        root_span_type: Optional[str] = None,
        root_span_name: Optional[str] = None,
        tags: Optional[dict[str, str]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """Create a new trace record. Returns the trace_id."""
        assert self._conn is not None
        tid = trace_id or str(uuid.uuid4())

        await self._conn.execute(
            """INSERT INTO traces (id, conversation_id, root_span_type,
               root_span_name, tags, metadata)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                tid,
                conversation_id,
                root_span_type,
                root_span_name,
                json.dumps(tags) if tags else None,
                json.dumps(metadata) if metadata else None,
            ),
        )
        await self._conn.commit()
        return tid

    async def finalize_trace(self, trace_id: str) -> None:
        """Compute and update summary stats for a completed trace."""
        assert self._conn is not None

        cursor = await self._conn.execute(
            """SELECT
                COUNT(*) as span_count,
                SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as error_count,
                MAX(end_time) as latest_end,
                MIN(start_time) as earliest_start,
                SUM(latency_ms) as total_latency_ms
               FROM spans WHERE trace_id = ?""",
            (trace_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return

        earliest = row["earliest_start"]
        latest = row["latest_end"]
        total_latency = None
        if earliest and latest:
            # Parse ISO datetime strings
            try:
                from datetime import datetime as dt
                e = dt.fromisoformat(earliest.replace("Z", "+00:00"))
                l = dt.fromisoformat(latest.replace("Z", "+00:00"))
                total_latency = (l - e).total_seconds() * 1000
            except (ValueError, TypeError):
                pass

        # Collect unique MCP servers
        cursor2 = await self._conn.execute(
            """SELECT DISTINCT mcp_server_name FROM spans
               WHERE trace_id = ? AND mcp_server_name IS NOT NULL""",
            (trace_id,),
        )
        servers = [r[0] for r in await cursor2.fetchall()]

        await self._conn.execute(
            """UPDATE traces SET
               span_count = ?, error_count = ?,
               total_latency_ms = ?,
               mcp_servers = ?
               WHERE id = ?""",
            (
                row["span_count"],
                row["error_count"],
                total_latency,
                json.dumps(servers),
                trace_id,
            ),
        )
        await self._conn.commit()

    # ------------------------------------------------------------------
    # Span lifecycle
    # ------------------------------------------------------------------

    async def start_span(
        self,
        trace_id: str,
        span_type: MCPSpanType | str,
        parent_span_id: Optional[str] = None,
        mcp_server_name: Optional[str] = None,
        mcp_server_version: Optional[str] = None,
        mcp_transport: Optional[str] = None,
        mcp_request_method: Optional[str] = None,
        mcp_request_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        tool_arguments: Optional[dict[str, Any]] = None,
        tool_call_id: Optional[str] = None,
        attributes: Optional[dict[str, Any]] = None,
    ) -> str:
        """Start a new span. Returns the span_id."""
        assert self._conn is not None
        sid = str(uuid.uuid4())

        span_type_str = (
            span_type.value if isinstance(span_type, MCPSpanType) else span_type
        )

        await self._conn.execute(
            """INSERT INTO spans (id, trace_id, parent_span_id, span_type,
               mcp_server_name, mcp_server_version, mcp_transport,
               mcp_request_method, mcp_request_id,
               tool_name, tool_arguments, tool_call_id,
               attributes_json, start_time)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
            (
                sid,
                trace_id,
                parent_span_id,
                span_type_str,
                mcp_server_name,
                mcp_server_version,
                mcp_transport,
                mcp_request_method,
                mcp_request_id,
                tool_name,
                json.dumps(tool_arguments) if tool_arguments else None,
                tool_call_id,
                json.dumps(attributes) if attributes else None,
            ),
        )
        await self._conn.commit()
        return sid

    async def finish_span(
        self,
        span_id: str,
        *,
        latency_ms: float,
        result_content: Optional[list[Any]] = None,
        result_size_bytes: Optional[int] = None,
        result_is_error: bool = False,
        upstream_llm_tokens: Optional[int] = None,
        downstream_llm_tokens: Optional[int] = None,
        status: str = "ok",
        attributes: Optional[dict[str, Any]] = None,
    ) -> None:
        """Finish a span with result metadata."""
        assert self._conn is not None

        # Build preview from content
        preview = None
        if result_content:
            try:
                raw = json.dumps(result_content, default=str)
                preview = raw[:500]
                if result_size_bytes is None:
                    result_size_bytes = len(raw)
            except (TypeError, ValueError):
                preview = str(result_content)[:500]

        await self._conn.execute(
            """UPDATE spans SET
               end_time = datetime('now'),
               latency_ms = ?,
               result_content_preview = ?,
               result_size_bytes = ?,
               result_is_error = ?,
               upstream_llm_tokens = ?,
               downstream_llm_tokens = ?,
               status = ?,
               attributes_json = COALESCE(attributes_json, '{}') || ?
               WHERE id = ?""",
            (
                latency_ms,
                preview,
                result_size_bytes,
                1 if result_is_error else 0,
                upstream_llm_tokens,
                downstream_llm_tokens,
                status,
                json.dumps(attributes) if attributes else "{}",
                span_id,
            ),
        )
        await self._conn.commit()

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    async def get_trace(
        self,
        trace_id: str,
    ) -> Optional[tuple[dict, list[dict]]]:
        """Get a trace and all its spans."""
        assert self._conn is not None

        cursor = await self._conn.execute(
            "SELECT * FROM traces WHERE id = ?",
            (trace_id,),
        )
        trace_row = await cursor.fetchone()
        if not trace_row:
            return None

        cursor2 = await self._conn.execute(
            "SELECT * FROM spans WHERE trace_id = ? ORDER BY start_time",
            (trace_id,),
        )
        span_rows = await cursor2.fetchall()

        return (dict(trace_row), [dict(r) for r in span_rows])

    async def list_traces(
        self,
        limit: int = 20,
        offset: int = 0,
        mcp_server: Optional[str] = None,
        time_from: Optional[datetime] = None,
        time_to: Optional[datetime] = None,
    ) -> list[dict]:
        """List traces with optional filters."""
        assert self._conn is not None

        query = "SELECT * FROM traces WHERE 1=1"
        params: list[Any] = []

        if mcp_server:
            query += " AND mcp_servers LIKE ?"
            params.append(f"%{mcp_server}%")
        if time_from:
            query += " AND timestamp >= ?"
            params.append(time_from.isoformat())
        if time_to:
            query += " AND timestamp <= ?"
            params.append(time_to.isoformat())

        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor = await self._conn.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_mcp_server_stats(self) -> list[dict]:
        """Get aggregated stats per MCP server."""
        assert self._conn is not None

        cursor = await self._conn.execute("""
            SELECT
                mcp_server_name,
                COUNT(*) as call_count,
                AVG(latency_ms) as avg_latency_ms,
                MAX(latency_ms) as max_latency_ms,
                SUM(result_size_bytes) as total_result_bytes,
                SUM(CASE WHEN result_is_error THEN 1 ELSE 0 END) as error_count
            FROM spans
            WHERE mcp_server_name IS NOT NULL
              AND span_type = 'mcp.tool.call'
            GROUP BY mcp_server_name
            ORDER BY call_count DESC
        """)
        return [dict(r) for r in await cursor.fetchall()]

    async def get_tool_stats(
        self,
        mcp_server: Optional[str] = None,
    ) -> list[dict]:
        """Get aggregated stats per MCP tool."""
        assert self._conn is not None

        query = """
            SELECT
                mcp_server_name,
                tool_name,
                COUNT(*) as call_count,
                AVG(latency_ms) as avg_latency_ms,
                MIN(latency_ms) as min_latency_ms,
                MAX(latency_ms) as max_latency_ms,
                AVG(result_size_bytes) as avg_result_bytes,
                SUM(CASE WHEN result_is_error THEN 1 ELSE 0 END) as error_count
            FROM spans
            WHERE span_type = 'mcp.tool.call'
              AND tool_name IS NOT NULL
        """
        params: list[Any] = []
        if mcp_server:
            query += " AND mcp_server_name = ?"
            params.append(mcp_server)

        query += " GROUP BY mcp_server_name, tool_name ORDER BY call_count DESC"

        cursor = await self._conn.execute(query, params)
        return [dict(r) for r in await cursor.fetchall()]

    async def cleanup_old_traces(self, retention_days: int = 30) -> int:
        """Delete traces older than retention_days. Returns count deleted."""
        assert self._conn is not None
        cutoff = datetime.utcnow() - timedelta(days=retention_days)

        cursor = await self._conn.execute(
            "DELETE FROM traces WHERE timestamp < ?",
            (cutoff.isoformat(),),
        )
        await self._conn.commit()
        return cursor.rowcount
