"""WorkBuddy adapter (Tencent's desktop agent, a CodeBuddy product): ``~/.workbuddy/projects/<project>/<session>.jsonl``.

Each line is one item of the conversation, in the style of the OpenAI Responses API:

* ``message`` (``role`` user/assistant, ``input_text`` / ``output_text`` parts),
* ``reasoning`` (the model's thinking, in ``rawContent``),
* ``function_call`` (``callId``, ``name``, ``arguments`` as a JSON string) and
  ``function_call_result`` (``callId``, ``output``),
* bookkeeping: ``ai-title``, ``file-history-snapshot``.

All items of one model response share ``providerData.messageId``. The token usage of a
response (``providerData.rawUsage``, also ``message.usage``) sits on one item of it, usually the
first tool call or the final message. ``prompt_tokens`` includes the cached part.

The transcript does not record the system prompt or the tool schemas, so the context
breakdown is estimated, not exact.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional

from ..cost.pricing import usage_cost
from . import models as M
from .claude_code import _clip, classify_text, read_rows
from .models import Event, ParsedSession, SessionMeta, Step

AGENT = "workbuddy"
SEARCH_TEXT_CAP = 150_000
# A user message is the app's context (OS, time, memory reminders) followed by what the user typed:
#   <system-reminder data-role="user-context">...</system-reminder><user_query>the prompt</user_query>
REMINDER = re.compile(r"<system-reminder\b[^>]*>.*?</system-reminder>", re.S)
QUERY = re.compile(r"<user_query>(.*?)</user_query>", re.S)


def split_user_text(text: str) -> tuple[str, str]:
    """(injected context, what the user typed) of a user message."""
    context = "\n".join(m.group(0) for m in REMINDER.finditer(text))
    rest = REMINDER.sub("", text).strip()
    query = QUERY.search(rest)
    return context, (query.group(1).strip() if query else rest)


def workbuddy_root() -> str:
    base = os.environ.get("WORKBUDDY_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".workbuddy")
    return os.path.join(base, "projects")


def discover(root: str) -> list[str]:
    found: list[str] = []
    if not os.path.isdir(root):
        return found
    for project in os.scandir(root):
        if not project.is_dir(follow_symlinks=False):
            continue
        for f in os.scandir(project.path):
            if f.name.endswith(".jsonl") and f.is_file(follow_symlinks=False):
                found.append(f.path)
    return found


def _iso(ms: Any) -> Optional[str]:
    if not isinstance(ms, (int, float)):
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(ms) % 1000:03d}Z"


def _ms(a: Any, b: Any) -> Optional[float]:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return max(0.0, float(b) - float(a))
    return None


def _text_of(content: Any) -> str:
    """Text of a content list: ``input_text`` / ``output_text`` / ``text`` parts; others as a marker."""
    if isinstance(content, str):
        return content
    parts = []
    for p in content or []:
        if isinstance(p, dict):
            t = p.get("text")
            parts.append(t if isinstance(t, str) else f"[{str(p.get('type', 'block')).replace('_blob_ref', '')}]")
    return "\n".join(x for x in parts if x)


def _maybe_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _usage_of(r: dict[str, Any]) -> Optional[dict[str, int]]:
    """Normalised usage of an item, or None when it carries none."""
    pd = r.get("providerData") or {}
    raw = pd.get("rawUsage")
    alt = (r.get("message") or {}).get("usage") if isinstance(r.get("message"), dict) else None
    if not isinstance(raw, dict) and not isinstance(alt, dict):
        return None
    raw = raw if isinstance(raw, dict) else {}
    alt = alt if isinstance(alt, dict) else {}
    prompt = int(raw.get("prompt_tokens") or alt.get("input_tokens") or 0)
    details = raw.get("prompt_tokens_details") if isinstance(raw.get("prompt_tokens_details"), dict) else {}
    cached = max(
        int(raw.get("prompt_cache_hit_tokens") or 0),
        int(raw.get("cache_read_input_tokens") or 0),
        int(raw.get("cached_tokens") or 0),
        int(details.get("cached_tokens") or 0),
        int(alt.get("cache_read_input_tokens") or 0),
    )
    written = int(raw.get("cache_creation_input_tokens") or raw.get("prompt_cache_write_tokens") or 0)
    output = int(raw.get("completion_tokens") or alt.get("output_tokens") or 0)
    return {"input": max(0, prompt - cached - written), "output": output, "cache_read": cached, "cache_write": written}


def _result_text(item: dict[str, Any]) -> str:
    out = item.get("output")
    if isinstance(out, str):
        return out
    if isinstance(out, dict):
        return str(out.get("text") or "")
    if isinstance(out, list):
        return _text_of(out)
    tr = (item.get("providerData") or {}).get("toolResult") or {}
    return str(tr.get("content") or "")


def parse(path: str) -> ParsedSession:
    stat = os.stat(path)
    meta = SessionMeta(id=os.path.splitext(os.path.basename(path))[0], agent=AGENT, path=path, size_bytes=stat.st_size,
                       fidelity="estimated")
    ps = ParsedSession(meta=meta)

    turn = 0
    first_prompt = ""
    title = ""
    models_seen: list[str] = []
    search: list[str] = []
    search_len = 0
    last_input_ms: Optional[float] = None
    pending: dict[str, list[int]] = {}  # messageId -> events waiting for the usage of their response
    step_of: dict[str, Step] = {}
    call_ms: dict[str, float] = {}
    call_step: dict[str, Optional[Step]] = {}
    call_event: dict[str, Event] = {}
    last_ms: Any = None

    def add(kind: str, ms: Any, text: str = "", **kw: Any) -> Event:
        ev = Event(idx=len(ps.events), kind=kind, ts=_iso(ms), turn=turn, text=_clip(text), **kw)
        ps.events.append(ev)
        return ev

    def remember(text: str) -> None:
        nonlocal search_len
        if search_len < SEARCH_TEXT_CAP and text:
            search.append(text)
            search_len += len(text)

    def attach(ev: Event, mid: Optional[str], model: Optional[str]) -> None:
        """Tie an assistant-side event to its model response (a step), now or when its usage arrives."""
        if not mid:
            return
        ev.model = model
        st = step_of.get(mid)
        if st is not None:
            ev.step = st.index
            if ev.kind == M.TOOL_CALL and ev.tool_use_id:
                call_step[ev.tool_use_id] = st
        else:
            pending.setdefault(mid, []).append(ev.idx)

    def open_step(mid: str, usage: dict[str, int], model: str, ms: Any) -> None:
        if mid in step_of:
            return
        waiting = pending.pop(mid, [])
        step = Step(
            index=len(ps.steps),
            turn=turn,
            model=model,
            ts=_iso(last_input_ms),
            end_ts=_iso(ms),
            msg_id=mid,
            input_tokens=usage["input"],
            output_tokens=usage["output"],
            cache_read_tokens=usage["cache_read"],
            cache_write_tokens=usage["cache_write"],
            request_ts=_iso(last_input_ms),
            first_event=waiting[0] if waiting else len(ps.events),
            system_key=None,
        )
        step.model_ms = _ms(last_input_ms, ms)
        ps.steps.append(step)
        step_of[mid] = step
        for idx in waiting:
            ev = ps.events[idx]
            ev.step = step.index
            if ev.kind == M.TOOL_CALL and ev.tool_use_id:
                call_step[ev.tool_use_id] = step
        if model not in models_seen:
            models_seen.append(model)

    for r in read_rows(path):
        t = r.get("type")
        ms = r.get("timestamp")
        pd = r.get("providerData") or {}
        if isinstance(ms, (int, float)):
            last_ms = ms
            meta.started_at = meta.started_at or _iso(ms)
        meta.project = r.get("cwd") or meta.project
        if r.get("sessionId"):
            meta.id = str(r["sessionId"])
        mid = pd.get("messageId")
        model = pd.get("model") or pd.get("requestModelId") or pd.get("requestModelName")

        if t == "ai-title":
            title = str(r.get("aiTitle") or title)
        elif t == "message":
            role = r.get("role")
            text = _text_of(r.get("content"))
            if role == "user":
                if pd.get("isSummary") or pd.get("isCompacted"):
                    add(M.COMPACTION, ms, text, label="summary")
                    continue
                if not text.strip():
                    continue
                injected, typed = split_user_text(text)
                if injected:
                    add(M.CONTEXT, ms, injected, label="system-reminder")
                if typed:
                    kind, label = classify_text(typed)
                    if kind == M.CONTEXT:
                        add(M.CONTEXT, ms, typed, label=label)
                    else:
                        turn += 1
                        first_prompt = first_prompt or typed
                        remember(typed)
                        add(M.USER, ms, typed)
                last_input_ms = ms
            elif role == "assistant":
                if pd.get("error"):
                    add(M.SYSTEM_EVENT, ms, str(pd["error"]) if not isinstance(pd["error"], dict) else json.dumps(pd["error"]),
                        label="error")
                elif text.strip():
                    remember(text)
                    attach(add(M.ASSISTANT, ms, text), mid, model)
                usage = _usage_of(r)
                if usage and mid:
                    open_step(mid, usage, model or "unknown", ms)
        elif t == "reasoning":
            text = _text_of(r.get("rawContent")) or _text_of(r.get("content"))
            attach(add(M.THINKING, ms, text), mid, model)
        elif t == "function_call":
            call_id = r.get("callId")
            ev = add(M.TOOL_CALL, ms, "", tool_name=r.get("name"), tool_input=_maybe_json(r.get("arguments")),
                     tool_use_id=call_id)
            if call_id:
                call_ms[call_id] = ms
                call_event[call_id] = ev
            attach(ev, mid, model)
            usage = _usage_of(r)
            if usage and mid:
                open_step(mid, usage, model or "unknown", ms)
        elif t == "function_call_result":
            call_id = r.get("callId")
            failed = str(r.get("status") or "completed") in ("failed", "error", "rejected", "cancelled")
            add(M.TOOL_RESULT, ms, _result_text(r), tool_use_id=call_id, is_error=failed)
            last_input_ms = ms
            st = call_step.get(call_id or "")
            took = _ms(call_ms.get(call_id or ""), ms)
            if st is not None and took is not None:
                st.tools_ms = max(st.tools_ms or 0.0, took)

    meta.ended_at = _iso(last_ms) or meta.started_at
    total: Optional[float] = None
    for st in ps.steps:
        cost = usage_cost(st.model, st.usage())
        st.cost_usd = cost
        if cost is not None:
            total = (total or 0.0) + cost
    meta.tool_calls = sum(1 for e in ps.events if e.kind == M.TOOL_CALL)
    meta.messages = sum(1 for e in ps.events if e.kind in (M.USER, M.ASSISTANT))
    meta.turns = turn
    meta.steps = len(ps.steps)
    meta.models = models_seen
    meta.cost_usd = round(total, 6) if total is not None else None
    line = (title or first_prompt).strip().splitlines()[0] if (title or first_prompt).strip() else ""
    meta.title = (line or meta.id)[:200]
    ps.search_text = "\n".join(search)[:SEARCH_TEXT_CAP]
    return ps
