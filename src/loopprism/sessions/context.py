"""Per-step context breakdown: what filled the model's input, by category.

Real token counts come from the usage the model reported for each step. How
that total splits across categories is estimated from the text of each piece
and scaled so the parts add up to the reported total ("Estimated ≈17.2k,
Actual 17.3k"). Where the transcript records the real request (Claude Code
≥ 2.1.308) the *content* of every piece is exact; otherwise the system prompt
and tool schemas are inferred as whatever the conversation doesn't explain.
"""

from __future__ import annotations

import json
from bisect import bisect_left
from typing import Any, Optional

from . import models as M
from .claude_code import classify_text
from .models import ParsedSession, Step
from .tokens import estimate_json, estimate_text

CATEGORIES = [
    ("system_prompt", "System Prompt"),
    ("tool_schemas", "Tool Schemas"),
    ("user", "User Messages"),
    ("injected", "Injected Context"),
    ("skills", "Skill Injections"),
    ("assistant", "Assistant Messages"),
    ("tool_results", "Tool Results"),
    ("unattributed", "System & tools (inferred)"),
]
LABELS = dict(CATEGORIES)

# Context windows (tokens). Prefix match on the model id; Codex reports its own.
WINDOW_PREFIXES = [
    # 1M-token windows on the current Claude lineup; older models 200k.
    ("claude-fable", 1_000_000),
    ("claude-mythos", 1_000_000),
    ("claude-opus-5", 1_000_000),
    ("claude-opus-4-8", 1_000_000),
    ("claude-sonnet-5", 1_000_000),
    ("claude-haiku-5", 1_000_000),
    ("claude-", 200_000),
    ("gpt-", 400_000),
    ("deepseek", 128_000),
]

PREVIEW = 160
IMAGE_TOKENS = 1500  # a typical screenshot after the API's downscaling


def window_for(step: Step) -> tuple[Optional[int], str]:
    if step.context_window:
        return step.context_window, "reported"
    for prefix, size in WINDOW_PREFIXES:
        if step.model.startswith(prefix):
            return size, "assumed"
    return None, "unknown"


def tokenizer_factor(model: str) -> float:
    """Claude 4.7+ tokenizes ~30% more finely than the chars/3.8 heuristic assumes."""
    if model.startswith(("claude-fable", "claude-mythos", "claude-opus-5", "claude-sonnet-5", "claude-haiku-5", "claude-opus-4-8", "claude-opus-4-7")):
        return 1.35
    return 1.0


def _text_blocks(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [b for b in (content or []) if isinstance(b, dict)]


def _count_images(content: Any) -> int:
    if isinstance(content, list):
        return sum(1 for b in content if isinstance(b, dict) and b.get("type") == "image")
    return 0


def _tool_result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(
        (b.get("text") or f"[{b.get('type')}]") for b in (content or []) if isinstance(b, dict)
    )


def classify_message(msg: dict[str, Any]) -> list[tuple[str, str, float, str]]:
    """Split one request message into (category, label, est_tokens, preview)."""
    role = msg.get("role")
    out: list[tuple[str, str, float, str]] = []
    for b in _text_blocks(msg.get("content")):
        bt = b.get("type")
        if role == "assistant":
            if bt == "tool_use":
                text = json.dumps({"name": b.get("name"), "input": b.get("input")}, ensure_ascii=False)
                out.append(("assistant", f"tool call · {b.get('name')}", estimate_text(text), text[:PREVIEW]))
            elif bt == "thinking":
                text = b.get("thinking") or ""
                sig = len(b.get("signature") or "")
                out.append(("assistant", "thinking", estimate_text(text) + sig / 4, text[:PREVIEW] or "(thinking)"))
            else:
                text = b.get("text") or ""
                out.append(("assistant", "assistant", estimate_text(text), text[:PREVIEW]))
        elif bt == "tool_result":
            text = _tool_result_text(b.get("content"))
            est = estimate_text(text) + IMAGE_TOKENS * _count_images(b.get("content"))
            out.append(("tool_results", "tool result", est, text[:PREVIEW]))
        elif bt == "text":
            text = b.get("text") or ""
            kind, label = classify_text(text)
            if role == "system" and kind == M.USER:
                kind, label = M.CONTEXT, "system"
            if kind == M.CONTEXT:
                cat = "skills" if label == "skill" else "injected"
                out.append((cat, label or "context", estimate_text(text), text.strip()[:PREVIEW]))
            else:
                out.append(("user", "user", estimate_text(text), text[:PREVIEW]))
        elif bt == "image":
            out.append(("user", "image", float(IMAGE_TOKENS), "[image]"))
        else:
            out.append(("injected", bt or "block", estimate_json(b), json.dumps(b, ensure_ascii=False)[:PREVIEW]))
    return out


def _event_item(e: M.Event) -> Optional[tuple[str, str, float, str]]:
    k = e.kind
    if k == M.USER:
        return ("user", "user", estimate_text(e.text), e.text[:PREVIEW])
    if k == M.CONTEXT:
        cat = "skills" if e.label == "skill" else "injected"
        return (cat, e.label or "context", estimate_text(e.text), e.text.strip()[:PREVIEW])
    if k == M.ASSISTANT:
        return ("assistant", "assistant", estimate_text(e.text), e.text[:PREVIEW])
    if k == M.THINKING:
        return ("assistant", "thinking", estimate_text(e.text) + 20, e.text[:PREVIEW] or "(thinking)")
    if k == M.TOOL_CALL:
        text = json.dumps({"name": e.tool_name, "input": e.tool_input}, ensure_ascii=False, default=str)
        return ("assistant", f"tool call · {e.tool_name}", estimate_text(text), text[:PREVIEW])
    if k == M.TOOL_RESULT:
        return ("tool_results", "tool result", estimate_text(e.text) + IMAGE_TOKENS * e.text.count("[image]"), e.text[:PREVIEW])
    if k == M.COMPACTION:
        return ("user", "compaction summary", estimate_text(e.text), e.text[:PREVIEW])
    return None


def _shape_items(ps: ParsedSession, step: Step) -> tuple[list, list]:
    shape = ps.shapes.get(step.system_key or "") or {}
    sys_items = []
    for i, b in enumerate(shape.get("system") or []):
        text = b.get("text") if isinstance(b, dict) else str(b)
        sys_items.append(("system_prompt", f"system block {i + 1}", estimate_text(text or ""), (text or "").strip()[:PREVIEW]))
    tool_items = []
    for t in shape.get("tools") or []:
        name = t.get("name", "tool") if isinstance(t, dict) else "tool"
        tool_items.append(("tool_schemas", name, estimate_json(t), (t.get("description", "") if isinstance(t, dict) else "")[:PREVIEW]))
    return sys_items, tool_items


class StepContext:
    """Items sent for one step plus the scaling to the reported total."""

    def __init__(self, items: list, actual: int, inferred: bool, factor: float = 1.0) -> None:
        self.items = items
        self.actual = actual
        est = sum(i[2] for i in items) * factor
        self.factor = factor
        self.estimated = est
        self.inferred = inferred
        if inferred:
            self.unattributed = max(0.0, actual - est) if actual else 0.0
            self.scale = actual / est if est and actual and est > actual else 1.0
        else:
            self.unattributed = 0.0
            self.scale = actual / est if est and actual else 1.0

    def totals(self) -> dict[str, float]:
        out: dict[str, float] = {k: 0.0 for k, _ in CATEGORIES}
        for cat, _label, est, _p in self.items:
            out[cat] += est * self.factor * self.scale
        out["unattributed"] = self.unattributed
        return out


def _event_items(ps: ParsedSession) -> tuple[list[int], list, list[int]]:
    """Per-event context items (main thread only), computed once per session."""
    cached = getattr(ps, "_ev_items", None)
    if cached is not None:
        return cached
    idxs: list[int] = []
    items: list = []
    resets: list[int] = []  # positions in `items` where a compaction restarts the context
    for e in ps.events:
        if e.sidechain:
            continue
        it = _event_item(e)
        if e.kind == M.COMPACTION and e.label in ("summary", "compact_boundary"):
            resets.append(len(items))
        if it:
            idxs.append(e.idx)
            items.append(it)
    ps._ev_items = (idxs, items, resets)  # type: ignore[attr-defined]
    return ps._ev_items  # type: ignore[attr-defined]


def _items_for_step(ps: ParsedSession, step: Step, msg_cache: dict[str, list]) -> tuple[list, bool, Optional[list[str]]]:
    """(items, inferred, ref_hashes_or_None) for the request this step sent."""
    sys_items, tool_items = _shape_items(ps, step)
    if step.refs is not None:
        items = list(sys_items) + list(tool_items)
        for h in step.refs:
            cl = msg_cache.get(h)
            if cl is None:
                m = ps.pool.get(h)
                cl = classify_message(m) if m else []
                msg_cache[h] = cl
            items.extend(cl)
        return items, not (sys_items or tool_items), step.refs
    # Rebuild from the conversation so far (prefix of the per-event items, from
    # the last compaction on).
    idxs, evitems, resets = _event_items(ps)
    hi = bisect_left(idxs, step.first_event)
    lo = 0
    r = bisect_left(resets, hi)  # resets are positions in evitems
    if r > 0:
        lo = resets[r - 1]
    items = list(sys_items) + list(tool_items) + evitems[lo:hi]
    return items, not (sys_items or tool_items), None


def step_context(ps: ParsedSession, index: int, detail: bool = False) -> dict[str, Any]:
    step = ps.steps[index]
    cache: dict[str, list] = getattr(ps, "_msg_cache", None) or {}
    ps._msg_cache = cache  # type: ignore[attr-defined]
    items, inferred, refs = _items_for_step(ps, step, cache)
    ctx = StepContext(items, step.total_input, inferred, tokenizer_factor(step.model))
    totals = ctx.totals()
    window, window_src = window_for(step)
    cats = []
    for key, label in CATEGORIES:
        if key == "unattributed" and not inferred:
            continue
        n = sum(1 for i in items if i[0] == key)
        cats.append({"key": key, "label": label, "tokens": round(totals[key]), "items": n})
    total = sum(c["tokens"] for c in cats) or 1
    for c in cats:
        c["pct"] = round(100 * c["tokens"] / total, 1)
    out = {
        "step": step.index,
        "turn": step.turn,
        "ts": step.ts,
        "model": step.model,
        "sidechain": step.sidechain,
        "exact_request": step.refs is not None,
        "actual_input": step.total_input,
        "estimated_input": round(ctx.estimated),
        "window": window,
        "window_source": window_src,
        "window_pct": round(100 * step.total_input / window, 1) if window else None,
        "output_tokens": step.output_tokens,
        "cache_hit_pct": round(100 * step.cache_read_tokens / step.total_input, 2) if step.total_input else None,
        "cost_usd": step.cost_usd,
        "categories": cats,
    }
    if detail:
        scale = ctx.scale
        by_cat: dict[str, list] = {}
        for cat, label, est, preview in items:
            by_cat.setdefault(cat, []).append({"label": label, "tokens": round(est * ctx.factor * scale), "preview": preview})
        if inferred and ctx.unattributed:
            by_cat["unattributed"] = [{"label": "system prompt + tool schemas (not recorded)", "tokens": round(ctx.unattributed), "preview": ""}]
        out["items"] = by_cat
        out["message_hashes"] = refs
    return out


def trend(ps: ParsedSession) -> list[dict[str, Any]]:
    """Category totals for every non-synthetic step (for the stacked bar chart)."""
    done = getattr(ps, "_trend", None)
    if done is not None:
        return done
    cache: dict[str, list] = getattr(ps, "_msg_cache", None) or {}
    ps._msg_cache = cache  # type: ignore[attr-defined]
    out = []
    prev_total = 0
    for st in ps.steps:
        if st.model == "<synthetic>":
            continue
        items, inferred, _ = _items_for_step(ps, st, cache)
        ctx = StepContext(items, st.total_input, inferred, tokenizer_factor(st.model))
        totals = {k: round(v) for k, v in ctx.totals().items() if v}
        total = st.total_input
        out.append({
            "step": st.index,
            "turn": st.turn,
            "sidechain": st.sidechain,
            "total": total,
            "delta": total - prev_total,
            "categories": totals,
            "output_tokens": st.output_tokens,
            "cache_hit_pct": round(100 * st.cache_read_tokens / total, 2) if total else None,
        })
        if not st.sidechain:
            prev_total = total
    ps._trend = out  # type: ignore[attr-defined]
    return out


def stats(ps: ParsedSession) -> dict[str, Any]:
    main = [s for s in ps.steps if not s.sidechain and s.model != "<synthetic>"]
    sub = [s for s in ps.steps if s.sidechain]
    total_in = sum(s.total_input for s in main)
    cost = sum(s.cost_usd or 0 for s in main) if any(s.cost_usd is not None for s in main) else None
    sub_cost = sum(s.cost_usd or 0 for s in sub) if any(s.cost_usd is not None for s in sub) else None
    last = main[-1] if main else None
    window, src = window_for(last) if last else (None, "unknown")
    return {
        "turns": ps.meta.turns,
        "steps": len(main),
        "human_inputs": sum(1 for e in ps.events if e.kind == M.USER and not e.sidechain),
        "tool_calls": sum(1 for e in ps.events if e.kind == M.TOOL_CALL and not e.sidechain),
        "cache_hit_pct": round(100 * sum(s.cache_read_tokens for s in main) / total_in, 2) if total_in else None,
        "cost_usd": round(cost, 6) if cost is not None else None,
        "subagent_cost_usd": round(sub_cost, 6) if sub_cost is not None else None,
        "current_context": last.total_input if last else 0,
        "window": window,
        "window_source": src,
        "fidelity": ps.meta.fidelity,
        "unresolved_messages": ps.unresolved,
        "models": ps.meta.models,
    }
