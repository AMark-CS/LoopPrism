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
IDLE_CAP_MS = 5 * 60 * 1000


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
    # Wall clock of the turns: gaps between consecutive events, with long idle
    # stretches (waiting for you, a permission prompt, a closed laptop) capped.
    wall_ms = 0.0
    last: dict[int, str] = {}
    from .claude_code import _ms

    for e in ps.events:
        if not e.ts or e.sidechain:
            continue
        prev = last.get(e.turn)
        if prev:
            d = _ms(prev, e.ts)
            if d:
                wall_ms += min(d, IDLE_CAP_MS)
        last[e.turn] = e.ts
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


COST_TYPE_LABELS = {
    "input": "Uncached input",
    "cache_read": "Cache reads",
    "cache_write": "Cache writes",
    "output": "Output",
}


def cost_breakdown(ps: ParsedSession) -> dict[str, Any]:
    """Where the (estimated, API list price) money went.

    Split four ways: by token type, by what filled the context (each step's
    input-side cost shared out by its context categories; generated output
    kept apart), by model, and by turn. Steps whose model has no published
    price are left out and counted in ``unpriced_steps``.
    """
    from ..cost.pricing import lookup
    from . import context

    trend = {p["step"]: p for p in context.trend(ps)}
    by_type = {k: 0.0 for k in COST_TYPE_LABELS}
    by_cat: dict[str, float] = defaultdict(float)
    by_model: dict[str, float] = defaultdict(float)
    by_turn: dict[int, float] = defaultdict(float)
    steps: list[tuple[float, int, int]] = []
    unpriced = 0
    subagent = 0.0
    per = 1_000_000

    for st in ps.steps:
        if st.model == "<synthetic>":
            continue
        pr = lookup(st.model)
        if pr is None:
            unpriced += 1
            continue
        if st.total_input > pr.long_context_threshold and pr.long_context is not None:
            pr = pr.long_context
        read_price = pr.input_cost_per_m if pr.cache_read_cost_per_m is None else pr.cache_read_cost_per_m
        w5 = pr.input_cost_per_m if pr.cache_write_cost_per_m is None else pr.cache_write_cost_per_m
        w1 = pr.input_cost_per_m if pr.cache_write_1h_cost_per_m is None else pr.cache_write_1h_cost_per_m
        c_in = st.input_tokens * pr.input_cost_per_m / per
        c_read = st.cache_read_tokens * read_price / per
        c_write = (st.cache_write_tokens * w5 + st.cache_write_1h_tokens * w1) / per
        c_out = st.output_tokens * pr.output_cost_per_m / per
        total = c_in + c_read + c_write + c_out
        by_type["input"] += c_in
        by_type["cache_read"] += c_read
        by_type["cache_write"] += c_write
        by_type["output"] += c_out
        by_model[st.model] += total
        by_turn[st.turn] += total
        steps.append((total, st.index, st.turn))
        if st.sidechain:
            subagent += total
        input_side = c_in + c_read + c_write
        cats = (trend.get(st.index) or {}).get("categories") or {}
        denom = sum(cats.values())
        if denom:
            for k, tokens in cats.items():
                by_cat[k] += input_side * tokens / denom
        else:
            by_cat["unattributed"] += input_side
        by_cat["output"] += c_out

    total = sum(by_type.values())
    cat_labels = {k: label for k, label in context.CATEGORIES}
    cat_labels["output"] = "Generated output"
    return {
        "total_usd": round(total, 6),
        "subagent_usd": round(subagent, 6) if subagent else None,
        "unpriced_steps": unpriced,
        "by_type": [{"key": k, "label": COST_TYPE_LABELS[k], "usd": round(v, 6)} for k, v in by_type.items() if v],
        "by_category": [
            {"key": k, "label": cat_labels.get(k, k), "usd": round(v, 6)}
            for k, v in sorted(by_cat.items(), key=lambda kv: -kv[1]) if v
        ],
        "by_model": [{"model": m, "usd": round(v, 6)} for m, v in sorted(by_model.items(), key=lambda kv: -kv[1])],
        "by_turn": [{"turn": t, "usd": round(v, 6)} for t, v in sorted(by_turn.items())],
        "top_steps": [
            {"step": i, "turn": t, "usd": round(c, 6)} for c, i, t in sorted(steps, reverse=True)[:5]
        ],
    }
