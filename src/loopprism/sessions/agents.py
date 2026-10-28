"""The agent tree of a session: the main agent and the subagents it spawned.

Claude Code keeps each subagent in its own transcript next to the session::

    <project>/<session>.jsonl                       main agent
    <project>/<session>/subagents/agent-<id>.jsonl  one file per subagent

The main transcript records the spawn (an ``Agent`` / ``Task`` tool call with
the task prompt) and, in the tool result or in a task notification, the
subagent's ``agentId``. A subagent can spawn subagents of its own, which are
recorded the same way inside its file, so the result is a tree.

Only Claude Code sessions are supported; Codex records spawned threads in a
different shape that is not read yet.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from datetime import datetime
from typing import Any, Iterable, Iterator, Optional

from . import claude_code
from . import models as M
from .models import ParsedSession
from .tokens import estimate_text

SPAWN_TOOLS = {"Agent", "Task"}
AGENT_ID = re.compile(r"^[A-Za-z0-9]{6,64}$")
_AGENT_ID_IN_TEXT = re.compile(r"agentId:\s*([A-Za-z0-9]{6,64})")
_NOTIFICATION = re.compile(r"<task-notification>(.*?)</task-notification>", re.S)
MAX_AGENTS = 300
TEXT_CAP = 20_000


def subagent_dir(session_path: str) -> str:
    return os.path.join(os.path.splitext(session_path)[0], "subagents")


def subagent_file(session_path: str, agent_id: str) -> str:
    return os.path.join(subagent_dir(session_path), f"agent-{agent_id}.jsonl")


# --------------------------------------------------------------------- scanning
def _strings(row: dict[str, Any]) -> Iterator[str]:
    """Places a task notification can appear in a transcript row."""
    c = row.get("content")
    if isinstance(c, str):
        yield c
    att = row.get("attachment")
    if isinstance(att, dict) and isinstance(att.get("prompt"), str):
        yield att["prompt"]
    m = row.get("message")
    if isinstance(m, dict) and isinstance(m.get("content"), str):
        yield m["content"]


def _tag(text: str, name: str) -> Optional[str]:
    m = re.search(rf"<{name}>(.*?)</{name}>", text, re.S)
    return m.group(1).strip() if m else None


def scan_rows(rows: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, dict[str, Any]]]:
    """Spawn calls, tool_use_id -> agentId links, and finish notifications."""
    spawns: list[dict[str, Any]] = []
    links: dict[str, str] = {}
    notes: dict[str, dict[str, Any]] = {}
    for r in rows:
        t = r.get("type")
        m = r.get("message")
        if t == "assistant" and isinstance(m, dict):
            for b in m.get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") in SPAWN_TOOLS:
                    inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                    spawns.append({
                        "tool_use_id": b.get("id"),
                        "ts": r.get("timestamp"),
                        "description": str(inp.get("description") or ""),
                        "prompt": str(inp.get("prompt") or ""),
                        "subagent_type": str(inp.get("subagent_type") or ""),
                        "background": bool(inp.get("run_in_background")),
                    })
        elif t == "user" and isinstance(m, dict) and isinstance(m.get("content"), list):
            for b in m["content"]:
                if not (isinstance(b, dict) and b.get("type") == "tool_result"):
                    continue
                tur = r.get("toolUseResult")
                aid = tur.get("agentId") if isinstance(tur, dict) else None
                if not aid:
                    hit = _AGENT_ID_IN_TEXT.search(claude_code._result_text(b.get("content")) or "")
                    aid = hit.group(1) if hit else None
                if b.get("tool_use_id") and aid:
                    links[b["tool_use_id"]] = str(aid)
        for s in _strings(r):
            if "<task-notification>" not in s:
                continue
            for body in _NOTIFICATION.findall(s):
                aid, uid = _tag(body, "task-id"), _tag(body, "tool-use-id")
                if not aid:
                    continue
                if uid:
                    links[uid] = aid
                nums = {k: _tag(body, k) for k in ("subagent_tokens", "tool_uses", "duration_ms")}
                notes[aid] = {
                    "status": _tag(body, "status"),
                    "tokens": int(nums["subagent_tokens"]) if (nums["subagent_tokens"] or "").isdigit() else None,
                    "tool_uses": int(nums["tool_uses"]) if (nums["tool_uses"] or "").isdigit() else None,
                    "duration_ms": int(nums["duration_ms"]) if (nums["duration_ms"] or "").isdigit() else None,
                }
    return spawns, links, notes


# ---------------------------------------------------------------------- helpers
def _ts(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _cap(text: str) -> tuple[str, bool]:
    return (text[:TEXT_CAP], len(text) > TEXT_CAP)


def _usage(steps: list[M.Step]) -> dict[str, int]:
    u = {
        "input": sum(s.input_tokens for s in steps),
        "output": sum(s.output_tokens for s in steps),
        "cache_read": sum(s.cache_read_tokens for s in steps),
        "cache_write": sum(s.cache_write_tokens + s.cache_write_1h_tokens for s in steps),
    }
    u["total"] = sum(u.values())
    return u


def _cost(steps: list[M.Step]) -> Optional[float]:
    costs = [s.cost_usd for s in steps if s.cost_usd is not None]
    return round(sum(costs), 6) if costs else None


def _stats(ps: ParsedSession, steps: list[M.Step], events: list[M.Event]) -> dict[str, Any]:
    models = Counter(s.model for s in steps)
    tools = Counter(e.tool_name for e in events if e.kind == M.TOOL_CALL and e.tool_name)
    return {
        "model": models.most_common(1)[0][0] if models else None,
        "models": list(models),
        "steps": len(steps),
        "tool_calls": sum(tools.values()),
        "tools": dict(tools.most_common(8)),
        "errors": sum(1 for e in events if e.kind == M.TOOL_RESULT and e.is_error),
        "cost_usd": _cost(steps),
        "tokens": _usage(steps),
    }


def _first_user(events: list[M.Event]) -> str:
    return next((e.text for e in events if e.kind == M.USER and e.text.strip()), "")


def _last_assistant(events: list[M.Event]) -> str:
    """What the subagent handed back: its hand-back call, else its last message."""
    for e in reversed(events):
        if e.kind == M.TOOL_CALL and e.tool_name == "SubagentHandback" and isinstance(e.tool_input, dict):
            msg = e.tool_input.get("message")
            if isinstance(msg, str) and msg.strip():
                return msg
    return next((e.text for e in reversed(events) if e.kind == M.ASSISTANT and e.text.strip()), "")


def _text_block(text: str) -> dict[str, Any]:
    shown, truncated = _cap(text)
    return {"text": shown, "tokens": round(estimate_text(text)), "estimated": True, "truncated": truncated}


def _peak_parallel(spans: list[tuple[float, float]]) -> int:
    marks = sorted([(a, 1) for a, _ in spans] + [(b, -1) for _, b in spans], key=lambda m: (m[0], m[1]))
    cur = peak = 0
    for _, d in marks:
        cur += d
        peak = max(peak, cur)
    return peak


# ------------------------------------------------------------------------ build
def unsupported(reason: str) -> dict[str, Any]:
    return {
        "supported": False,
        "reason": reason,
        "agents": [],
        "totals": {"subagents": 0, "peak_parallel": 0, "subagent_cost_usd": None, "main_cost_usd": None,
                   "total_cost_usd": None, "passed_tokens": 0},
    }


def build(ps: ParsedSession) -> dict[str, Any]:
    """The main agent plus every subagent it (transitively) spawned."""
    meta = ps.meta
    if meta.agent != "claude-code":
        return unsupported("Subagent trees are only read from Claude Code sessions for now.")

    main_steps = [s for s in ps.steps if not s.sidechain and s.model != "<synthetic>"]
    main_events = [e for e in ps.events if not e.sidechain]
    main = {
        "id": "main", "parent_id": None, "name": "Main agent", "role": "main", "description": "",
        "background": False, "status": "completed", "session_id": meta.id,
        "start": meta.started_at, "end": meta.ended_at, "spawned_at": None, "duration_ms": None,
        **_stats(ps, main_steps, main_events),
        "task": None, "result": None,
    }
    s0, s1 = _ts(meta.started_at), _ts(meta.ended_at)
    main["duration_ms"] = round((s1 - s0) * 1000) if s0 is not None and s1 is not None else None
    nodes = [main]

    seen: set[str] = set()
    queue: list[tuple[str, list[dict[str, Any]]]] = [("main", list(claude_code.read_rows(meta.path)))]
    while queue and len(nodes) < MAX_AGENTS:
        parent_id, rows = queue.pop(0)
        spawns, links, notes = scan_rows(rows)
        for sp in spawns:
            aid = links.get(sp["tool_use_id"] or "")
            node_id = aid or f"call-{(sp['tool_use_id'] or str(len(nodes)))[-10:]}"
            if node_id in seen:
                continue
            seen.add(node_id)
            note = notes.get(aid or "", {})
            path = subagent_file(meta.path, aid) if aid and AGENT_ID.match(aid) else None
            child_ps = claude_code.parse(path) if path and os.path.isfile(path) else None
            if child_ps is not None:
                steps = [s for s in child_ps.steps if s.model != "<synthetic>"]
                st = _stats(child_ps, steps, child_ps.events)
                task_text = sp["prompt"] or _first_user(child_ps.events)
                result_text = _last_assistant(child_ps.events)
                start, end = child_ps.meta.started_at, child_ps.meta.ended_at
                queue.append((node_id, list(claude_code.read_rows(path))))
            else:
                st = {"model": None, "models": [], "steps": 0, "tool_calls": note.get("tool_uses") or 0, "tools": {},
                      "errors": 0, "cost_usd": None, "tokens": {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0,
                                                              "total": note.get("tokens") or 0}}
                task_text, result_text, start, end = sp["prompt"], "", sp["ts"], None
            a0, a1 = _ts(start), _ts(end)
            duration = note.get("duration_ms")
            if duration is None and a0 is not None and a1 is not None:
                duration = round((a1 - a0) * 1000)
            status = (note.get("status") or ("completed" if result_text else "unknown")).lower()
            nodes.append({
                "id": node_id, "parent_id": parent_id,
                "name": sp["description"] or sp["subagent_type"] or "subagent",
                "role": sp["subagent_type"] or "subagent", "description": sp["description"],
                "background": sp["background"], "status": status,
                "session_id": f"{meta.id}~{aid}" if child_ps is not None else None,
                "start": start, "end": end, "spawned_at": sp["ts"], "duration_ms": duration,
                **st, "task": _text_block(task_text) if task_text else None,
                "result": _text_block(result_text) if result_text else None,
            })

    children = nodes[1:]
    spans = []
    for n in children:
        a, b = _ts(n["start"]), _ts(n["end"])
        if a is not None and b is not None and b >= a:
            spans.append((a, b))
    sub_cost = [n["cost_usd"] for n in children if n["cost_usd"] is not None]
    main_cost = main["cost_usd"]
    total = (main_cost or 0) + sum(sub_cost) if (main_cost is not None or sub_cost) else None
    return {
        "supported": True,
        "reason": None,
        "agents": nodes,
        "totals": {
            "subagents": len(children),
            "peak_parallel": _peak_parallel(spans),
            "subagent_cost_usd": round(sum(sub_cost), 6) if sub_cost else None,
            "main_cost_usd": main_cost,
            "total_cost_usd": round(total, 6) if total is not None else None,
            "passed_tokens": sum((n["task"] or {}).get("tokens", 0) + (n["result"] or {}).get("tokens", 0) for n in children),
        },
    }
