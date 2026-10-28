"""Findings and timing derived from a parsed session."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any

from . import models as M
from .models import ParsedSession

REPEAT_THRESHOLD = 3
ERROR_STREAK = 3


def _digest(value: Any) -> str:
    return hashlib.sha1(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:12]


def findings(ps: ParsedSession) -> list[dict[str, Any]]:
    """Loops and failure patterns: the things worth looking at first."""
    out: list[dict[str, Any]] = []

    # The same tool called with the same input again and again, within a turn.
    seen: dict[tuple[int, str, str], list[int]] = defaultdict(list)
    for e in ps.events:
        if e.kind == M.TOOL_CALL and not e.sidechain:
            seen[(e.turn, e.tool_name or "", _digest(e.tool_input))].append(e.idx)
    for (turn, tool, _), idxs in seen.items():
        if len(idxs) >= REPEAT_THRESHOLD:
            out.append({
                "kind": "repeated_call",
                "severity": "warn",
                "title": f"{tool} called {len(idxs)}× with identical input",
                "turn": turn,
                "events": idxs,
            })

    # Consecutive failing tool results.
    streak: list[int] = []
    for e in ps.events:
        if e.kind != M.TOOL_RESULT:
            continue
        if e.is_error:
            streak.append(e.idx)
            continue
        if len(streak) >= ERROR_STREAK:
            out.append({"kind": "error_streak", "severity": "error", "title": f"{len(streak)} tool errors in a row", "turn": ps.events[streak[0]].turn, "events": streak})
        streak = []
    if len(streak) >= ERROR_STREAK:
        out.append({"kind": "error_streak", "severity": "error", "title": f"{len(streak)} tool errors in a row", "turn": ps.events[streak[0]].turn, "events": streak})

    # Context compacted: the model lost detail here.
    for e in ps.events:
        if e.kind == M.COMPACTION and e.label in ("compact_boundary", "summary", "compaction"):
            out.append({"kind": "compaction", "severity": "info", "title": "Context was compacted", "turn": e.turn, "events": [e.idx]})
    out.sort(key=lambda f: f["events"][0])
    return out


def timing(ps: ParsedSession) -> dict[str, Any]:
    """Where the time went, from transcript timestamps (approximate).

    Exact time-to-first-token and streaming rates need the API capture proxy.
    """
    steps = [s for s in ps.steps if not s.sidechain and s.model != "<synthetic>"]
    model_ms = sum(s.model_ms or 0 for s in steps)
    thinking_ms = min(model_ms, sum(s.thinking_ms or 0 for s in steps))
    tools_ms = sum(s.tools_ms or 0 for s in steps)
    out_tokens = sum(s.output_tokens for s in steps if s.model_ms)
    # Wall clock of the turns themselves (user think time between turns excluded).
    wall_ms = 0.0
    by_turn: dict[int, list[str]] = defaultdict(list)
    for e in ps.events:
        if e.ts and not e.sidechain and e.turn:
            by_turn[e.turn].append(e.ts)
    from .claude_code import _ms

    for stamps in by_turn.values():
        d = _ms(min(stamps), max(stamps))
        if d:
            wall_ms += d
    active = model_ms + tools_ms
    overhead = max(0.0, wall_ms - active)
    return {
        "approximate": True,
        "model_ms": round(model_ms),
        "thinking_ms": round(thinking_ms),
        "answer_ms": round(max(0.0, model_ms - thinking_ms)),
        "tools_ms": round(tools_ms),
        "overhead_ms": round(overhead),
        "wall_ms": round(wall_ms),
        "tokens_per_second": round(out_tokens / (model_ms / 1000), 1) if model_ms else None,
        "steps": [
            {"step": s.index, "turn": s.turn, "model_ms": s.model_ms, "thinking_ms": s.thinking_ms, "tools_ms": s.tools_ms, "output_tokens": s.output_tokens}
            for s in steps
        ],
    }
