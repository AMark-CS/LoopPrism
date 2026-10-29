"""Rules that look at the sessions behind the Cost page and say what would have cost less.

Every rule works on one parsed session and returns findings with an estimated saving in USD,
computed by re-pricing the same tokens: a cheaper model for the same tokens, cache reads instead
of uncached input, fewer repeated calls. The savings are estimates, not promises: each finding
carries a confidence, and the total is de-duplicated per session (two rules that touch the same
tokens cannot save more than the session cost).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ..cost.pricing import lookup, usage_cost
from ..sessions import analysis
from ..sessions import models as M
from ..sessions.models import ParsedSession, Step
from ..sessions.tokens import estimate_text

MAX_SESSIONS = 80  # the most expensive sessions of the period; the rest is a long tail
SESSION_CAP = 0.8  # no session can be made more than 80% cheaper by suggestions

# Cheaper model of the same family for work that does not need the big one.
DOWNGRADE = [
    ("claude-fable", "claude-sonnet-5-5"),
    ("claude-opus", "claude-sonnet-5-5"),
    ("claude-sonnet", "claude-haiku-5-5"),
    ("gpt-6-astra", "gpt-6.1-sol"),
    ("gpt-6.1-sol", "gpt-6.1-terra"),
    ("gpt-5", "gpt-6.1-terra"),
    ("glm-5", "glm-4.5-air"),
    ("qwen3-max", "qwen-plus"),
    ("qwen3-coder-plus", "qwen3-coder-flash"),
    ("gemini-2.5-pro", "gemini-2.5-flash"),
    ("gemini-3-pro", "gemini-3-flash"),
]


@dataclass
class Finding:
    rule: str
    session_id: str
    saving: float
    detail: str
    confidence: str  # "high" | "medium" | "low"
    extra: dict[str, Any] = field(default_factory=dict)


def _unit_prices(model: str) -> Optional[tuple[float, float, float]]:
    """(uncached input, cache read, output) USD per token, or None when the model has no price."""
    p = lookup(model)
    if p is None:
        return None
    read = p.input_cost_per_m if p.cache_read_cost_per_m is None else p.cache_read_cost_per_m
    return p.input_cost_per_m / 1e6, read / 1e6, p.output_cost_per_m / 1e6


def _step_cost(st: Step) -> float:
    return st.cost_usd or 0.0


# ---------------------------------------------------------------------------- rules
def low_cache_hit(ps: ParsedSession) -> list[Finding]:
    """Most of the input was paid at full price although the same prefix is re-sent every step."""
    out: list[Finding] = []
    by_model: dict[str, list[Step]] = defaultdict(list)
    for st in ps.steps:
        by_model[st.model].append(st)
    for model, steps in by_model.items():
        prices = _unit_prices(model)
        if prices is None or prices[1] >= prices[0] or len(steps) < 6:
            continue  # no price, no cache discount, or too short to build a cache
        total = sum(s.total_input for s in steps)
        cached = sum(s.cache_read_tokens for s in steps)
        if total < 150_000 or cached / total >= 0.6:
            continue
        # The first step of every turn starts cold; assume 85% is the best a normal session reaches.
        reachable = max(0.0, 0.85 * total - cached)
        saving = reachable * (prices[0] - prices[1]) * 0.6  # 0.6: not all of it is within reach
        if saving > 0.01:
            note = " (some providers do not report cache reads at all)" if cached == 0 else ""
            out.append(Finding("low_cache_hit", ps.meta.id, saving,
                               f"{model}: {100 * cached / total:.0f}% of {total / 1000:.0f}k input tokens came from cache{note}",
                               "low" if cached == 0 else "medium", {"model": model, "hit_pct": round(100 * cached / total, 1)}))
    return out


def cheaper_model(ps: ParsedSession) -> list[Finding]:
    """A short, simple session that ran on the biggest model of its family."""
    main = [s for s in ps.steps if not s.sidechain]
    if not main or len(main) > 10 or sum(1 for e in ps.events if e.kind == M.TOOL_CALL) > 4:
        return []
    out_tokens = sum(s.output_tokens for s in main)
    if out_tokens > 3000:
        return []
    out: list[Finding] = []
    for model in {s.model for s in main}:
        alt = next((to for prefix, to in DOWNGRADE if model.lower().startswith(prefix)), None)
        if not alt or lookup(alt) is None or lookup(model) is None:
            continue
        steps = [s for s in main if s.model == model]
        now = sum(_step_cost(s) for s in steps)
        then = sum(usage_cost(alt, s.usage()) or 0.0 for s in steps)
        if now - then > 0.02:
            out.append(Finding("cheaper_model", ps.meta.id, now - then,
                               f"{len(steps)} steps, {out_tokens} output tokens, no heavy tool use: {model} → {alt}",
                               "medium", {"from": model, "to": alt}))
    return out


def repeated_calls(ps: ParsedSession) -> list[Finding]:
    """The same tool call with the same input again and again."""
    out: list[Finding] = []
    for f in analysis.findings(ps):
        if f["kind"] != "repeated_call":
            continue
        steps = {ps.events[i].step for i in f["events"] if ps.events[i].step is not None}
        costs = sorted((_step_cost(ps.steps[i]) for i in steps if i < len(ps.steps)), reverse=True)
        extra = sum(costs[1:])  # the first call was needed
        if extra > 0.01:
            out.append(Finding("repeated_calls", ps.meta.id, extra, f["title"], "medium", {"turn": f.get("turn")}))
    return out


def big_tool_output(ps: ParsedSession) -> list[Finding]:
    """A huge tool result is re-sent with every later step."""
    out: list[Finding] = []
    n_steps = len(ps.steps)
    results = [(e, estimate_text(e.text)) for e in ps.events if e.kind == M.TOOL_RESULT and not e.sidechain]
    results = [(e, t) for e, t in results if t >= 8000]
    if not results or not n_steps:
        return out
    model = next((s.model for s in ps.steps if _unit_prices(s.model)), None)
    prices = _unit_prices(model) if model else None
    if prices is None:
        return out
    total = 0.0
    biggest = 0
    for e, tokens in results:
        later = sum(1 for s in ps.steps if s.first_event > e.idx)
        kept = 3000  # a trimmed result (head and tail) is still plenty for the model
        saved_tokens = tokens - kept
        total += saved_tokens * (prices[0] + later * prices[1])
        biggest = max(biggest, tokens)
    if total > 0.02:
        out.append(Finding("big_tool_output", ps.meta.id, total * 0.7,
                           f"{len(results)} tool results over 8k tokens (largest ≈{biggest / 1000:.0f}k)", "low",
                           {"count": len(results), "largest_tokens": biggest}))
    return out


def long_session(ps: ParsedSession) -> list[Finding]:
    """A long session whose context keeps growing: every later step re-reads all of it."""
    main = [s for s in ps.steps if not s.sidechain]
    if len(main) < 40:
        return []
    keep = 40_000  # what a fresh session with a short summary would start from
    saved_tokens = 0
    cost_per_token = []
    for s in main:
        if s.total_input > 2 * keep:
            saved_tokens += s.total_input - keep
            p = _unit_prices(s.model)
            if p:
                cost_per_token.append(p[1] if s.cache_read_tokens > s.input_tokens else p[0])
    if not cost_per_token or saved_tokens < 1_000_000:
        return []
    saving = saved_tokens * (sum(cost_per_token) / len(cost_per_token)) * 0.4  # a summary and re-reading files cost something
    if saving < 0.05:
        return []
    last = main[-1].total_input
    return [Finding("long_session", ps.meta.id, saving,
                    f"{len(main)} steps, the context grew to {last / 1000:.0f}k tokens", "low", {"steps": len(main), "context": last})]


RULES: list[Callable[[ParsedSession], list[Finding]]] = [low_cache_hit, cheaper_model, repeated_calls, big_tool_output, long_session]

# What each rule says, in plain words.
COPY: dict[str, dict[str, str]] = {
    "low_cache_hit": {
        "title": "Use the prompt cache",
        "how": "Keep the start of the conversation stable (system prompt, tools, early messages) so it is cached. Avoid editing earlier messages or reordering tools mid-session, and keep working in one session instead of restarting it.",
        "tags": "cache context",
    },
    "cheaper_model": {
        "title": "Use a smaller model for simple tasks",
        "how": "Quick questions and small edits do not need the biggest model. Switch with /model (Claude Code) or your agent's model picker for short tasks.",
        "tags": "router gateway model",
    },
    "repeated_calls": {
        "title": "Stop repeated tool calls",
        "how": "The agent ran the same command or read the same file several times with identical input. Give it the result once (or a note in CLAUDE.md/AGENTS.md) and ask it not to repeat it.",
        "tags": "dedupe cache",
    },
    "big_tool_output": {
        "title": "Trim huge tool outputs",
        "how": "Large outputs (logs, whole files, search dumps) are re-sent with every later step. Use head/tail/grep, read line ranges, or a tool that compresses output before the model sees it.",
        "tags": "compress output",
    },
    "long_session": {
        "title": "Start a fresh session when the context gets long",
        "how": "Past ~100k tokens every step re-reads everything. Summarise the state (or use /compact, /clear) and continue in a new session.",
        "tags": "context compact",
    },
}


# ------------------------------------------------------------------------ driver
def analyze(sessions: list[dict[str, Any]], load: Callable[[str], Optional[ParsedSession]], spend: float) -> dict[str, Any]:
    """Run every rule over the given sessions (index rows); returns suggestions and the de-duplicated total."""
    findings: list[Finding] = []
    costs: dict[str, float] = {}
    meta: dict[str, dict[str, Any]] = {}
    for row in sessions[:MAX_SESSIONS]:
        ps = load(row["id"])
        if ps is None:
            continue
        costs[row["id"]] = row.get("cost_usd") or 0.0
        meta[row["id"]] = row
        for rule in RULES:
            try:
                findings += rule(ps)
            except Exception:  # one odd session must not hide the rest
                continue

    per_session: dict[str, float] = defaultdict(float)
    for f in findings:
        per_session[f.session_id] += f.saving
    # Findings of one session overlap (they re-price the same tokens): cap each session.
    scale = {sid: min(1.0, SESSION_CAP * costs[sid] / total) if total > 0 and costs.get(sid) else 1.0 for sid, total in per_session.items()}
    total_saving = sum(min(total, SESSION_CAP * costs.get(sid, total)) for sid, total in per_session.items())

    suggestions = []
    for rule, copy in COPY.items():
        fs = sorted((f for f in findings if f.rule == rule), key=lambda f: -f.saving)
        if not fs:
            continue
        saving = sum(f.saving * scale.get(f.session_id, 1.0) for f in fs)
        order = {"high": 2, "medium": 1, "low": 0}
        confidence = min((f.confidence for f in fs), key=lambda c: order[c])
        suggestions.append({
            "id": rule,
            "title": copy["title"],
            "how": copy["how"],
            "tags": copy["tags"].split(),
            "confidence": confidence,
            "saving_usd": round(saving, 4),
            "saving_pct": round(100 * saving / spend, 1) if spend else 0.0,
            "sessions": len({f.session_id for f in fs}),
            "evidence": [{
                "session_id": f.session_id,
                "title": meta[f.session_id].get("title"),
                "agent": meta[f.session_id].get("agent"),
                "detail": f.detail,
                "saving_usd": round(f.saving * scale.get(f.session_id, 1.0), 4),
            } for f in fs[:8]],
        })
    suggestions.sort(key=lambda s: -s["saving_usd"])
    total_saving = min(total_saving, spend) if spend else 0.0
    return {
        "spend_usd": round(spend, 4),
        "saving_usd": round(total_saving, 4),
        "optimized_usd": round(max(0.0, spend - total_saving), 4),
        "saving_pct": round(100 * total_saving / spend, 1) if spend else 0.0,
        "analyzed_sessions": len(costs),
        "suggestions": suggestions,
    }
