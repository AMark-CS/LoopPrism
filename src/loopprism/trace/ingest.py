"""Ingest of agent lifecycle events (Claude Code / Codex hooks).

Unlike the MCP proxy, which only sees MCP calls, hooks report everything the
agent does: built-in tools, shell commands, file edits, and the prompts that
started each piece of work. Events become runs and spans in the same store:

* a user prompt opens a **run** (one task, prompt to final answer)
* every tool call becomes an ``agent.tool.call`` **span** in that run
* the agent's ``Stop`` closes the run; a run left open when the next prompt or
  the session end arrives is marked ``abandoned``

Hooks run as short-lived processes, so all state lives in the database.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .collector import TraceCollector

AGENT_RUN = "agent.run"
AGENT_TOOL_CALL = "agent.tool.call"

PROMPT_PREVIEW_CHARS = 80
MAX_STRING_CHARS = 2000
MAX_DEPTH = 6


def truncate(value: Any, limit: int = MAX_STRING_CHARS, depth: int = 0) -> Any:
    """Cap string lengths and nesting so one huge tool payload stays small."""
    if isinstance(value, str):
        if len(value) <= limit:
            return value
        return f"{value[:limit]}... [{len(value) - limit} more chars]"
    if depth >= MAX_DEPTH:
        return "..."
    if isinstance(value, dict):
        return {str(k): truncate(v, limit, depth + 1) for k, v in list(value.items())[:50]}
    if isinstance(value, (list, tuple)):
        return [truncate(v, limit, depth + 1) for v in list(value)[:50]]
    return value


def split_mcp_tool(tool_name: str) -> tuple[Optional[str], str]:
    """``mcp__github__search`` -> (``github``, ``search``); others -> (None, name)."""
    if tool_name.startswith("mcp__"):
        _, _, rest = tool_name.partition("mcp__")
        server, sep, tool = rest.partition("__")
        if sep and server and tool:
            return server, tool
    return None, tool_name


def _sqlite_utc(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


class AgentIngestor:
    """Turns agent hook events into runs and spans."""

    def __init__(self, collector: TraceCollector) -> None:
        self.collector = collector
        # Hooks for one session can arrive concurrently (parallel tool calls).
        self._lock = asyncio.Lock()

    async def handle(self, event: dict[str, Any]) -> dict[str, Any]:
        kind = event.get("event")
        async with self._lock:
            if kind == "prompt":
                return await self._prompt(event)
            if kind in ("tool", "tool_failure"):
                return await self._tool(event)
            if kind == "stop":
                return await self._close(event, "succeeded")
            if kind == "session_end":
                return await self._close(event, "abandoned")
            if kind == "session_start":
                return {"ignored": "session_start"}
        return {"ignored": f"unknown event {kind!r}"}

    # ------------------------------------------------------------------

    async def _new_run(self, event: dict[str, Any], name: str) -> str:
        return await self.collector.create_trace(
            session_id=event["session_id"],
            correlation_source="explicit",
            root_span_type=AGENT_RUN,
            root_span_name=name,
            tags={"agent": event.get("agent", "unknown")},
            metadata=truncate(
                {k: event.get(k) for k in ("cwd", "model", "turn_id") if event.get(k)}
            ),
        )

    async def _prompt(self, event: dict[str, Any]) -> dict[str, Any]:
        sid = event["session_id"]
        previous = await self.collector.find_open_run(sid)
        if previous:
            # The agent never reported Stop for the last run.
            await self.collector.finalize_trace(previous)
            await self.collector.close_run(previous, "abandoned")
        prompt = (event.get("prompt") or "").strip().replace("\n", " ")
        name = prompt[:PROMPT_PREVIEW_CHARS] or "(prompt)"
        run_id = await self._new_run(event, name)
        return {"run_id": run_id, "abandoned": previous}

    async def _tool(self, event: dict[str, Any]) -> dict[str, Any]:
        sid = event["session_id"]
        run_id = await self.collector.find_open_run(sid)
        if run_id is None:
            # Hooks installed mid-session, or the prompt hook was missed.
            run_id = await self._new_run(event, "(no prompt captured)")

        raw_name = event.get("tool_name") or "unknown"
        server, tool = split_mcp_tool(raw_name)
        failed = event.get("event") == "tool_failure"
        duration_ms = float(event.get("duration_ms") or 0)

        started_at = _sqlite_utc(
            datetime.now(timezone.utc) - timedelta(milliseconds=duration_ms)
        )
        attributes: dict[str, Any] = {"agent": event.get("agent", "unknown")}
        if server is None:
            attributes["builtin"] = True
        if event.get("model"):
            attributes["model"] = event["model"]
        if failed and event.get("error"):
            attributes["error"] = truncate(event["error"], 500)

        span_id = await self.collector.start_span(
            trace_id=run_id,
            span_type=AGENT_TOOL_CALL,
            mcp_server_name=server,
            tool_name=tool,
            tool_arguments=truncate(event.get("tool_input")) or None,
            tool_call_id=event.get("tool_use_id"),
            attributes=attributes,
            started_at=started_at,
        )
        response = event.get("tool_response")
        await self.collector.finish_span(
            span_id,
            latency_ms=duration_ms,
            result_content=[truncate(response)] if response not in (None, "") else None,
            result_size_bytes=(
                len(json.dumps(response, default=str)) if response is not None else 0
            ),
            result_is_error=failed,
            status="error" if failed else "ok",
        )
        await self.collector.finalize_trace(run_id)
        return {"run_id": run_id, "span_id": span_id}

    async def _close(self, event: dict[str, Any], default_status: str) -> dict[str, Any]:
        run_id = await self.collector.find_open_run(event["session_id"])
        if run_id is None:
            return {"closed": None}
        await self.collector.finalize_trace(run_id)
        status = default_status
        if event.get("outcome") == "failed":
            status = "failed"
        await self.collector.close_run(run_id, status, event.get("outcome"))
        return {"closed": run_id, "status": status}
