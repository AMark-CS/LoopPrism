"""Claude Code adapter: ``~/.claude/projects/<project>/<session>.jsonl``.

Newer Claude Code versions also log the exact request each model call sent
(``api-request`` + ``api-request-shape`` + ``api-request-blob`` records). Those
make the Context view exact; for older sessions the request is rebuilt from the
conversation and the system prompt / tool schemas are inferred.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from typing import Any, Iterable, Optional

from ..cost.pricing import usage_cost
from . import models as M
from .models import Event, ParsedSession, SessionMeta, Step

AGENT = "claude-code"
CONTEXT_TAGS = (
    "<system-reminder>",
    "<local-command-",
    "<command-stdout>",
    "<user-prompt-submit-hook>",
)
LONG_CONTEXT_TOKENS = 100_000
MAX_MODEL_MS = 30 * 60 * 1000
SEARCH_TEXT_CAP = 150_000


def message_hash(message: dict[str, Any]) -> str:
    """Claude Code's content hash of a request message (sha256 of canonical JSON)."""
    blob = json.dumps(message, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


def classify_text(text: str) -> tuple[str, Optional[str]]:
    """Is a user-role text block typed by the human, or injected by the harness?"""
    head = text.lstrip()[:300]
    if "This session is being continued from a previous conversation" in head:
        return M.COMPACTION, None
    if "Base directory for this skill" in text[:300] or head.startswith("Launching skill"):
        return M.CONTEXT, "skill"
    if head.startswith(CONTEXT_TAGS) or head.startswith("Caveat:"):
        return M.CONTEXT, "system-reminder"
    return M.USER, None


def _blocks(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [b for b in (content or []) if isinstance(b, dict)]


def _result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for b in content or []:
        if isinstance(b, dict):
            parts.append(b.get("text") if b.get("type") == "text" else f"[{b.get('type', 'block')}]")
    return "\n".join(p for p in parts if p)


def _ms(a: Optional[str], b: Optional[str]) -> Optional[float]:
    if not a or not b:
        return None
    try:
        da = datetime.fromisoformat(a.replace("Z", "+00:00"))
        db = datetime.fromisoformat(b.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (db - da).total_seconds() * 1000)


def read_rows(path: str) -> Iterable[dict[str, Any]]:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                yield row


def _clip(text: str) -> str:
    return text if len(text) <= M.MAX_EVENT_CHARS else text[: M.MAX_EVENT_CHARS] + f"... [{len(text) - M.MAX_EVENT_CHARS} more chars]"


def parse(path: str, standalone: bool = False) -> ParsedSession:
    """Parse a transcript. ``standalone`` reads a subagent's own file as a conversation of
    its own, instead of flagging its rows as a sidechain of another session."""
    stat = os.stat(path)
    rows = list(read_rows(path))
    sid = os.path.splitext(os.path.basename(path))[0]
    meta = SessionMeta(id=sid, agent=AGENT, path=path, size_bytes=stat.st_size)
    ps = ParsedSession(meta=meta)

    def side(row: dict[str, Any]) -> bool:
        return False if standalone else bool(row.get("isSidechain"))

    # ---- pass 1: message pool (so request records can be resolved) ---------
    blobs: dict[str, dict[str, Any]] = {}
    assistant_msgs: dict[str, dict[str, Any]] = {}
    user_run: list[list[dict[str, Any]]] = []  # consecutive user messages
    for r in rows:
        t = r.get("type")
        if t == "api-request-blob" and isinstance(r.get("message"), dict):
            blobs[r.get("hash", "")] = r["message"]
        elif t == "user" and isinstance(r.get("message"), dict):
            m = r["message"]
            ps.pool[message_hash({"role": m.get("role", "user"), "content": m.get("content")})] = {
                "role": m.get("role", "user"),
                "content": m.get("content"),
            }
            # The API merges adjacent user messages (parallel tool results,
            # then the next prompt) into one; index those merges too.
            user_run.append(_blocks(m.get("content")))
            for start in range(max(0, len(user_run) - 8), len(user_run) - 1):
                merged = [b for part in user_run[start:] for b in part]
                ps.pool[message_hash({"role": "user", "content": merged})] = {"role": "user", "content": merged}
        elif t == "assistant" and isinstance(r.get("message"), dict):
            user_run = []
            m = r["message"]
            a = assistant_msgs.setdefault(m.get("id") or r.get("uuid", ""), {"role": "assistant", "content": []})
            a["content"].extend(m.get("content") or [])
    for a in assistant_msgs.values():
        ps.pool[message_hash(a)] = a
    for h, m in blobs.items():
        ps.pool[h] = m
    for r in rows:
        if r.get("type") == "api-request-shape" and r.get("shapeHash"):
            ps.shapes[r["shapeHash"]] = r.get("shape") or {}

    # ---- pass 2: events and steps -----------------------------------------
    turn = 0
    title_custom = ""
    title_agent = ""
    last_prompt = ""
    first_prompt = ""
    pending_requests: list[dict[str, Any]] = []
    request_lists: dict[str, list[str]] = {}
    steps_by_msg: dict[str, Step] = {}
    last_model: Optional[str] = None
    tool_use_ts: dict[str, str] = {}
    tool_use_step: dict[str, Step] = {}
    search: list[str] = []
    search_len = 0
    models_seen: list[str] = []
    exact_steps = 0

    def add(kind: str, row: dict[str, Any], text: str = "", **kw: Any) -> Event:
        ev = Event(
            idx=len(ps.events),
            kind=kind,
            ts=row.get("timestamp"),
            turn=turn,
            text=_clip(text),
            sidechain=side(row),
            **kw,
        )
        ps.events.append(ev)
        return ev

    for r in rows:
        t = r.get("type")
        ts = r.get("timestamp")
        if ts:
            meta.started_at = meta.started_at or ts
            meta.ended_at = ts
        if r.get("cwd") and not meta.project:
            meta.project = r["cwd"]
        if r.get("version"):
            meta.version = r["version"]
        if r.get("gitBranch"):
            meta.git_branch = r["gitBranch"]

        if t == "custom-title":
            title_custom = r.get("customTitle") or title_custom
        elif t == "agent-name":
            title_agent = r.get("agentName") or title_agent
        elif t == "last-prompt":
            last_prompt = r.get("lastPrompt") or last_prompt
        elif t == "api-request":
            pending_requests.append(r)
            base = request_lists.get(r.get("base") or "", [])
            request_lists[r.get("id", "")] = base[: int(r.get("keep") or 0)] + list(r.get("tail") or [])
        elif t == "attachment":
            att = r.get("attachment") or {}
            text = ""
            for b in r.get("rendered") or []:
                if isinstance(b, dict):
                    text += (b.get("content") if isinstance(b.get("content"), str) else b.get("text", "")) or ""
            if not text:
                text = json.dumps(att, ensure_ascii=False, default=str)
            add(M.CONTEXT, r, text, label=att.get("type") or "attachment")
        elif t == "system":
            sub = r.get("subtype") or "system"
            if sub == "compact_boundary":
                add(M.COMPACTION, r, r.get("content") or "Conversation compacted", label=sub)
            else:
                add(M.SYSTEM_EVENT, r, r.get("content") or json.dumps({k: v for k, v in r.items() if k in ("hookCount", "stopReason", "level")}), label=sub)
        elif t == "user" and isinstance(r.get("message"), dict):
            content = r["message"].get("content")
            sidechain = side(r)
            if r.get("isCompactSummary"):
                add(M.COMPACTION, r, _result_text(content) if not isinstance(content, str) else content, label="summary")
                continue
            for b in _blocks(content):
                bt = b.get("type")
                if bt == "tool_result":
                    text = _result_text(b.get("content"))
                    uid = b.get("tool_use_id")
                    add(M.TOOL_RESULT, r, text, tool_use_id=uid, is_error=bool(b.get("is_error")))
                    st = tool_use_step.get(uid or "")
                    if st is not None and ts and tool_use_ts.get(uid or ""):
                        d = _ms(tool_use_ts[uid], ts)
                        if d is not None:
                            st.tools_ms = max(st.tools_ms or 0.0, d)
                elif bt == "text":
                    text = b.get("text") or ""
                    if not text.strip():
                        continue
                    kind, label = classify_text(text)
                    if kind == M.USER and not sidechain:
                        turn += 1
                        first_prompt = first_prompt or text
                        if search_len < SEARCH_TEXT_CAP:
                            search.append(text)
                            search_len += len(text)
                    add(kind, r, text, label=label)
                elif bt == "image":
                    add(M.USER, r, "[image]")
        elif t == "assistant" and isinstance(r.get("message"), dict):
            m = r["message"]
            mid = m.get("id") or r.get("uuid") or ""
            model = m.get("model") or "unknown"
            step = steps_by_msg.get(mid)
            if step is None:
                if model != "<synthetic>" and last_model and model != last_model and not side(r):
                    add(M.MODEL_CHANGE, r, f"model changed: {last_model} → {model}", model=model)
                if model != "<synthetic>" and not side(r):
                    last_model = model
                    if model not in models_seen:
                        models_seen.append(model)
                step = Step(
                    index=len(ps.steps),
                    turn=turn,
                    model=model,
                    ts=ts,
                    msg_id=mid,
                    sidechain=side(r),
                    first_event=len(ps.events),
                )
                # The request that produced this response is the latest one logged
                # before it; earlier unmatched ones were aborted or background calls.
                req = pending_requests[-1] if pending_requests else None
                pending_requests.clear()
                if req is not None:
                    step.request_ts = req.get("timestamp")
                    step.refs = request_lists.get(req.get("id", ""))
                    step.system_key = req.get("shapeHash")
                    exact_steps += 1
                ps.steps.append(step)
                steps_by_msg[mid] = step
            step.end_ts = ts or step.end_ts
            u = m.get("usage") or {}
            cc = u.get("cache_creation") or {}
            step.input_tokens = max(step.input_tokens, int(u.get("input_tokens") or 0))
            step.output_tokens = max(step.output_tokens, int(u.get("output_tokens") or 0))
            step.cache_read_tokens = max(step.cache_read_tokens, int(u.get("cache_read_input_tokens") or 0))
            if "ephemeral_5m_input_tokens" in cc or "ephemeral_1h_input_tokens" in cc:
                step.cache_write_tokens = max(step.cache_write_tokens, int(cc.get("ephemeral_5m_input_tokens") or 0))
                step.cache_write_1h_tokens = max(step.cache_write_1h_tokens, int(cc.get("ephemeral_1h_input_tokens") or 0))
            else:
                step.cache_write_tokens = max(step.cache_write_tokens, int(u.get("cache_creation_input_tokens") or 0))
            if r.get("thinkingDurationMs"):
                step.thinking_ms = max(step.thinking_ms or 0.0, float(r["thinkingDurationMs"]))
            for b in m.get("content") or []:
                if not isinstance(b, dict):
                    continue
                bt = b.get("type")
                if bt == "thinking":
                    add(M.THINKING, r, b.get("thinking") or "", step=step.index, model=model)
                elif bt == "text":
                    text = b.get("text") or ""
                    if text.strip():
                        add(M.ASSISTANT, r, text, step=step.index, model=model)
                        if search_len < SEARCH_TEXT_CAP and not side(r):
                            search.append(text)
                            search_len += len(text)
                elif bt == "tool_use":
                    uid = b.get("id")
                    add(M.TOOL_CALL, r, "", step=step.index, model=model, tool_name=b.get("name"),
                        tool_input=b.get("input"), tool_use_id=uid)
                    if uid:
                        tool_use_step[uid] = step
                        if ts:
                            tool_use_ts[uid] = ts

    # ---- finish steps: cost, timing, request-relative fields ---------------
    total_cost: Optional[float] = None
    for st in ps.steps:
        if st.model == "<synthetic>":
            continue
        cost = usage_cost(st.model, {**st.usage(), "long_context": st.total_input > LONG_CONTEXT_TOKENS})
        st.cost_usd = cost
        if cost is not None:
            total_cost = (total_cost or 0.0) + cost
        if st.request_ts and st.end_ts:
            d = _ms(st.request_ts, st.end_ts)
            # A model call lasting over 30 minutes is a mispairing, not data.
            st.model_ms = d if d is not None and d <= MAX_MODEL_MS else None
    # Resolve event.step for events created before their step existed is not
    # needed: every assistant event is created with its step.

    for ev in ps.events:
        if ev.kind == M.TOOL_CALL:
            meta.tool_calls += 1
    meta.messages = sum(1 for e in ps.events if e.kind in (M.USER, M.ASSISTANT))
    meta.turns = turn
    meta.steps = sum(1 for s in ps.steps if not s.sidechain and s.model != "<synthetic>")
    meta.subagent_steps = sum(1 for s in ps.steps if s.sidechain)
    meta.models = models_seen
    meta.cost_usd = round(total_cost, 6) if total_cost is not None else None
    meta.fidelity = "exact" if ps.steps and exact_steps >= len([s for s in ps.steps if s.model != "<synthetic>"]) * 0.9 and exact_steps else "estimated"
    first_line = (first_prompt or last_prompt).strip().splitlines()[0] if (first_prompt or last_prompt).strip() else ""
    meta.title = (title_custom or title_agent or first_line or sid)[:200]
    ps.search_text = "\n".join(search)[:SEARCH_TEXT_CAP]

    # unresolved request messages: refs whose message we could not locate
    seen: set[str] = set()
    for st in ps.steps:
        for h in st.refs or []:
            if h not in ps.pool and h not in seen:
                seen.add(h)
    ps.unresolved = len(seen)
    return ps
