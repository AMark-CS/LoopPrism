"""Run correlation — decides which run (trace) an incoming MCP request belongs to.

The proxy tries these strategies in order and records which one succeeded in
``correlation_source`` so later analysis knows how far to trust the grouping
(see docs/run-data-model.md):

1. ``explicit``   W3C ``traceparent`` (HTTP header or ``params._meta``), or the
                  ``X-LoopPrism-Trace-Id`` header.
2. ``session``    ``Mcp-Session-Id`` header: calls in the same MCP session share
                  a run until the session goes idle.
3. ``heuristic``  No session id: group by client identity (address and
                  user-agent) and start a new run after an idle gap.

For (2) and (3) a run also ends when the client re-sends ``initialize``.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

EXPLICIT = "explicit"
SESSION = "session"
HEURISTIC = "heuristic"

DEFAULT_IDLE_SECONDS = 30.0

_TRACEPARENT_RE = re.compile(
    r"^(?P<version>[0-9a-f]{2})-(?P<trace>[0-9a-f]{32})-"
    r"(?P<span>[0-9a-f]{16})-(?P<flags>[0-9a-f]{2})$"
)

# Prune the in-memory table once it grows past this many entries.
_PRUNE_THRESHOLD = 256


@dataclass(frozen=True)
class TraceParent:
    """A parsed W3C ``traceparent`` value."""

    trace_id: str
    parent_span_id: str


def parse_traceparent(value: Any) -> Optional[TraceParent]:
    """Parse a W3C traceparent; return None if absent or invalid."""
    if not isinstance(value, str):
        return None
    match = _TRACEPARENT_RE.match(value.strip().lower())
    if match is None or match["version"] == "ff":
        return None
    trace_id, span_id = match["trace"], match["span"]
    # All-zero ids are explicitly invalid in the spec.
    if set(trace_id) == {"0"} or set(span_id) == {"0"}:
        return None
    return TraceParent(trace_id=trace_id, parent_span_id=span_id)


@dataclass(frozen=True)
class Correlation:
    """Result of correlating one request."""

    trace_id: str
    source: str
    session_id: Optional[str] = None
    # Span id of the caller's span, when the client sent a traceparent.
    remote_parent_span_id: Optional[str] = None
    # Key under which implicit runs are tracked (None for explicit ones).
    key: Optional[str] = None


class RunCorrelator:
    """Maps requests to runs. Single-threaded (asyncio) use only."""

    def __init__(
        self,
        idle_seconds: float = DEFAULT_IDLE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.idle_seconds = idle_seconds
        self._clock = clock
        # key -> (trace_id, last_seen)
        self._runs: dict[str, tuple[str, float]] = {}

    def resolve(
        self,
        headers: Mapping[str, str],
        body: Mapping[str, Any],
        server_name: str,
        client: Optional[str] = None,
        method: Optional[str] = None,
    ) -> Correlation:
        """Pick the run for a request.

        Args:
            headers: Request headers (case-insensitive mapping, e.g. Starlette's).
            body: Parsed JSON-RPC body.
            server_name: Logical MCP server the request is addressed to.
            client: Caller's network address, used as a weak identity.
            method: JSON-RPC method; ``initialize`` starts a fresh run.
        """
        session_id = headers.get("mcp-session-id") or None

        # 1. Explicit
        explicit = self._explicit(headers, body)
        if explicit is not None:
            return Correlation(
                trace_id=explicit.trace_id,
                source=EXPLICIT,
                session_id=session_id,
                remote_parent_span_id=explicit.parent_span_id,
            )
        legacy = headers.get("x-loopprism-trace-id") or headers.get(
            "x-toolglass-trace-id"
        )
        if legacy:
            return Correlation(trace_id=legacy, source=EXPLICIT, session_id=session_id)

        # 2./3. Implicit: one tracked run per key, renewed after an idle gap.
        if session_id:
            key = f"session:{server_name}:{session_id}"
            source = SESSION
        else:
            ua = headers.get("user-agent", "")
            key = f"client:{client or '-'}:{ua}"
            source = HEURISTIC

        trace_id = self._touch(key, fresh=method == "initialize")
        return Correlation(
            trace_id=trace_id, source=source, session_id=session_id, key=key
        )

    def bind_session(
        self, server_name: str, session_id: str, correlation: Correlation
    ) -> None:
        """Attach a server-issued session id to an in-flight run.

        ``initialize`` carries no ``Mcp-Session-Id`` (the server assigns one in
        its response), so later requests would otherwise start a second run.
        """
        self._runs[f"session:{server_name}:{session_id}"] = (
            correlation.trace_id,
            self._clock(),
        )

    # ------------------------------------------------------------------

    @staticmethod
    def _explicit(
        headers: Mapping[str, str], body: Mapping[str, Any]
    ) -> Optional[TraceParent]:
        parsed = parse_traceparent(headers.get("traceparent"))
        if parsed is not None:
            return parsed
        params = body.get("params") if isinstance(body, Mapping) else None
        meta = params.get("_meta") if isinstance(params, Mapping) else None
        if isinstance(meta, Mapping):
            return parse_traceparent(meta.get("traceparent"))
        return None

    def _touch(self, key: str, fresh: bool) -> str:
        now = self._clock()
        entry = self._runs.get(key)
        if fresh or entry is None or now - entry[1] > self.idle_seconds:
            trace_id = str(uuid.uuid4())
        else:
            trace_id = entry[0]
        self._runs[key] = (trace_id, now)
        if len(self._runs) > _PRUNE_THRESHOLD:
            self._prune(now)
        return trace_id

    def _prune(self, now: float) -> None:
        stale = [k for k, (_, seen) in self._runs.items() if now - seen > self.idle_seconds]
        for k in stale:
            del self._runs[k]
