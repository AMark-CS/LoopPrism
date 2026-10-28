"""Codex adapter: ``~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl``."""

from __future__ import annotations

import json
import re
import os
from typing import Any, Optional

from ..cost.pricing import usage_cost
from . import models as M
from .claude_code import _clip, _ms, read_rows
from .models import Event, ParsedSession, SessionMeta, Step

AGENT = "codex"
SEARCH_TEXT_CAP = 150_000
CONTEXT_PREFIXES = ("<environment_context>", "<user_instructions>", "# AGENTS.md", "<permissions", "<turn_aborted>")


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for b in content or []:
        if isinstance(b, dict):
            t = b.get("text")
            parts.append(t if isinstance(t, str) else f"[{b.get('type', 'block')}]")
    return "\n".join(p for p in parts if p)


def _maybe_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def parse(path: str) -> ParsedSession:
    stat = os.stat(path)
    rows = list(read_rows(path))
    base = os.path.splitext(os.path.basename(path))[0]
    sid = base.split("rollout-", 1)[-1]
    # A long Codex session is stored in several rollout files, one per history page
    # (rollout-<time>-<session>_<thread>.jsonl), and every page carries the same session
    # id. Keep the pages apart, otherwise the list shows duplicates under one id.
    page = re.search(r"_([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})$", base)
    meta = SessionMeta(id=sid, agent=AGENT, path=path, size_bytes=stat.st_size, fidelity="exact")
    ps = ParsedSession(meta=meta)

    turn = 0
    model_of_turn: dict[str, str] = {}
    window: Optional[int] = None
    first_prompt = ""
    search: list[str] = []
    search_len = 0
    models_seen: list[str] = []
    system_texts: list[str] = []
    tools_schema: list[Any] = []
    saw_developer = False
    pending: list[int] = []  # assistant-side events of the response in flight
    last_input_ts: Optional[str] = None
    call_ts: dict[str, str] = {}
    call_step: dict[str, Step] = {}
    awaiting_calls: dict[str, Step] = {}

    def add(kind: str, row: dict[str, Any], text: str = "", **kw: Any) -> Event:
        ev = Event(idx=len(ps.events), kind=kind, ts=row.get("timestamp"), turn=turn, text=_clip(text), **kw)
        ps.events.append(ev)
        return ev

    for r in rows:
        t = r.get("type")
        p = r.get("payload") or {}
        ts = r.get("timestamp")
        if ts:
            meta.started_at = meta.started_at or ts
            meta.ended_at = ts

        if t == "session_meta":
            meta.project = p.get("cwd") or meta.project
            meta.id = p.get("id") or meta.id
            if page and "_" not in meta.id:
                meta.id = f"{meta.id}_{page.group(1)}"
            meta.version = p.get("cli_version") or meta.version
            meta.started_at = p.get("timestamp") or meta.started_at
        elif t == "turn_context":
            if p.get("turn_id") and p.get("model"):
                model_of_turn[p["turn_id"]] = p["model"]
            meta.project = meta.project or p.get("cwd")
        elif t == "response_item":
            pt = p.get("type")
            if pt == "additional_tools":
                tools_schema = p.get("tools") or tools_schema
            elif pt == "message":
                role = p.get("role")
                text = _text_of(p.get("content"))
                if not text.strip():
                    continue
                if role == "developer":
                    if not saw_developer:
                        system_texts.append(text)
                        saw_developer = True
                        add(M.SYSTEM, r, text, label="developer")
                    else:
                        add(M.CONTEXT, r, text, label="developer")
                elif role == "user":
                    if text.lstrip().startswith(CONTEXT_PREFIXES):
                        add(M.CONTEXT, r, text, label="user-context")
                    else:
                        turn += 1
                        first_prompt = first_prompt or text
                        if search_len < SEARCH_TEXT_CAP:
                            search.append(text)
                            search_len += len(text)
                        add(M.USER, r, text)
                    last_input_ts = ts
                elif role == "assistant":
                    ev = add(M.ASSISTANT, r, text)
                    pending.append(ev.idx)
                    if search_len < SEARCH_TEXT_CAP:
                        search.append(text)
                        search_len += len(text)
            elif pt == "reasoning":
                summary = " ".join(s.get("text", "") for s in p.get("summary") or [] if isinstance(s, dict))
                ev = add(M.THINKING, r, summary)
                pending.append(ev.idx)
            elif pt in ("function_call", "custom_tool_call", "local_shell_call"):
                name = p.get("name") or pt
                if p.get("namespace"):
                    name = f"{p['namespace']}.{name}"
                args = _maybe_json(p.get("arguments") if "arguments" in p else p.get("input") or p.get("action"))
                ev = add(M.TOOL_CALL, r, "", tool_name=name, tool_input=args, tool_use_id=p.get("call_id"))
                pending.append(ev.idx)
                if p.get("call_id"):
                    awaiting_calls[p["call_id"]] = None  # step assigned when the record arrives
                    call_ts[p["call_id"]] = ts or ""
            elif pt in ("function_call_output", "custom_tool_call_output", "local_shell_call_output"):
                cid = p.get("call_id")
                out = p.get("output")
                text = _text_of(out) if not isinstance(out, str) else out
                add(M.TOOL_RESULT, r, text, tool_use_id=cid)
                last_input_ts = ts
                st = call_step.get(cid or "")
                if st is not None and call_ts.get(cid or ""):
                    d = _ms(call_ts[cid], ts)
                    if d is not None:
                        st.tools_ms = max(st.tools_ms or 0.0, d)
            elif pt == "compaction":
                add(M.COMPACTION, r, "Context compacted", label="compaction")
        elif t == "event_msg":
            et = p.get("type")
            if et == "token_count":
                info = p.get("info") or {}
                window = info.get("model_context_window") or window
            elif et == "turn_aborted":
                add(M.SYSTEM_EVENT, r, f"turn aborted: {p.get('reason', '')}", label="turn_aborted")
        elif t == "token_usage_record":
            u = p.get("usage") or {}
            tid = p.get("turn_id") or ""
            model = model_of_turn.get(tid, "unknown")
            cached = int(u.get("cached_input_tokens") or 0)
            written = int(u.get("cache_write_input_tokens") or 0)
            step = Step(
                index=len(ps.steps),
                turn=turn,
                model=model,
                ts=ts,
                end_ts=ts,
                msg_id=p.get("response_id"),
                sidechain=bool(p.get("root_turn_id") and p.get("root_turn_id") != tid),
                input_tokens=max(0, int(u.get("input_tokens") or 0) - cached - written),
                output_tokens=int(u.get("output_tokens") or 0),
                cache_read_tokens=cached,
                cache_write_tokens=written,
                request_ts=last_input_ts,
                first_event=pending[0] if pending else len(ps.events),
                system_key="codex",
                context_window=int(window) if window else None,
            )
            step.model_ms = _ms(last_input_ts, ts)
            for idx in pending:
                ps.events[idx].step = step.index
                ps.events[idx].model = model
                if ps.events[idx].kind == M.TOOL_CALL and ps.events[idx].tool_use_id:
                    call_step[ps.events[idx].tool_use_id] = step
            pending = []
            ps.steps.append(step)
            if model not in models_seen and not step.sidechain:
                models_seen.append(model)

    ps.shapes["codex"] = {"system": [{"type": "text", "text": "\n\n".join(system_texts)}] if system_texts else [], "tools": tools_schema}

    total: Optional[float] = None
    for st in ps.steps:
        cost = usage_cost(st.model, st.usage())
        st.cost_usd = cost
        if cost is not None:
            total = (total or 0.0) + cost
    meta.tool_calls = sum(1 for e in ps.events if e.kind == M.TOOL_CALL)
    meta.messages = sum(1 for e in ps.events if e.kind in (M.USER, M.ASSISTANT))
    meta.turns = turn
    meta.steps = sum(1 for s in ps.steps if not s.sidechain)
    meta.subagent_steps = sum(1 for s in ps.steps if s.sidechain)
    meta.models = models_seen
    meta.cost_usd = round(total, 6) if total is not None else None
    line = first_prompt.strip().splitlines()[0] if first_prompt.strip() else ""
    meta.title = (line or meta.id)[:200]
    ps.search_text = "\n".join(search)[:SEARCH_TEXT_CAP]
    return ps
