"""Gemini CLI adapter: ``~/.gemini/tmp/<project>/chats/session-*.jsonl`` (older versions: ``session-*.json``).

A session file is one conversation. The current format is append-only JSON lines:

* a header ``{sessionId, projectHash, startTime, lastUpdated, kind}``,
* one record per message (``type`` user / gemini / info / error / warning; a ``gemini`` message
  carries its ``toolCalls`` with their results, its ``thoughts``, ``model`` and ``tokens``),
* edits of earlier records: ``{"$patch": ...}`` (content, tool results, removals, reordering),
  ``{"$rewindTo": id}`` (drop that message and everything after it) and ``{"$set": ...}``
  (metadata such as the summary).

Older versions wrote the same data as one JSON document with a ``messages`` list. The project's
working directory is in ``~/.gemini/tmp/<project>/.project_root``.

Token usage is exact per model response. Gemini's prompt count includes the cached part, and
thinking tokens are billed as output.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Optional

from ..cost.pricing import usage_cost
from . import models as M
from .claude_code import _clip, classify_text, read_rows
from .models import Event, ParsedSession, SessionMeta, Step

AGENT = "gemini"
SEARCH_TEXT_CAP = 150_000


def gemini_root() -> str:
    base = os.environ.get("GEMINI_CLI_HOME") or os.path.expanduser("~")
    return os.path.join(base, ".gemini", "tmp")


def discover(root: str) -> list[str]:
    """``<root>/<project>/chats/session-*.json[l]`` (a session written in both formats counts once)."""
    found: dict[str, str] = {}
    if not os.path.isdir(root):
        return []
    for project in os.scandir(root):
        chats = os.path.join(project.path, "chats")
        if not project.is_dir(follow_symlinks=False) or not os.path.isdir(chats):
            continue
        for f in os.scandir(chats):
            if f.is_file(follow_symlinks=False) and f.name.startswith("session-") and f.name.endswith((".json", ".jsonl")):
                stem = os.path.join(chats, f.name.rsplit(".json", 1)[0])
                if stem not in found or f.name.endswith(".jsonl"):
                    found[stem] = f.path
    return list(found.values())


def _project_of(path: str) -> Optional[str]:
    try:
        with open(os.path.join(os.path.dirname(os.path.dirname(path)), ".project_root"), encoding="utf-8") as fh:
            return fh.read().strip() or None
    except OSError:
        return None


def _text_of(content: Any) -> str:
    """Text of a Gemini ``PartListUnion``: a string, a part, or a list of them."""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        content = [content]
    parts = []
    for p in content or []:
        if isinstance(p, str):
            parts.append(p)
        elif isinstance(p, dict):
            if isinstance(p.get("text"), str):
                parts.append(p["text"])
            elif "inlineData" in p or "fileData" in p:
                parts.append("[attachment]")
    return "\n".join(x for x in parts if x)


def _result_text(call: dict[str, Any]) -> str:
    """The output a tool call returned to the model (falling back to what the UI showed)."""
    out = []
    res = call.get("result")
    for p in ([res] if isinstance(res, dict) else res or []):
        fr = p.get("functionResponse") if isinstance(p, dict) else None
        if isinstance(fr, dict):
            body = fr.get("response")
            if isinstance(body, dict):
                v = body.get("output", body.get("error"))
                out.append(v if isinstance(v, str) else json.dumps(body, ensure_ascii=False))
            elif body is not None:
                out.append(str(body))
        elif isinstance(p, str):
            out.append(p)
    if out:
        return "\n".join(out)
    shown = call.get("resultDisplay")
    return shown if isinstance(shown, str) else ""


def _apply_patch(order: list[str], msgs: dict[str, dict[str, Any]], patch: dict[str, Any]) -> None:
    edits = list(patch.get("updates") or [])
    if patch.get("id"):
        edits.append(patch)
    for e in edits:
        m = msgs.get(e.get("id"))
        if m is None:
            continue
        if "content" in e:
            m["content"] = e["content"]
        for tp in e.get("toolCalls") or []:
            for call in m.get("toolCalls") or []:
                if call.get("id") == tp.get("id") and "result" in tp:
                    call["result"] = tp["result"]
    for rid in patch.get("removeIds") or []:
        msgs.pop(rid, None)
        if rid in order:
            order.remove(rid)
    if patch.get("orderIds"):
        wanted = [i for i in patch["orderIds"] if i in msgs]
        order[:] = wanted + [i for i in order if i not in wanted]


def load(path: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """(header, messages in order) of a session file, with patches and rewinds applied."""
    header: dict[str, Any] = {}
    order: list[str] = []
    msgs: dict[str, dict[str, Any]] = {}

    def add(m: dict[str, Any]) -> None:
        if m["id"] not in msgs:
            order.append(m["id"])
        msgs[m["id"]] = m

    if path.endswith(".json"):
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            doc = {}
        if isinstance(doc, dict):
            header = {k: v for k, v in doc.items() if k != "messages"}
            for m in doc.get("messages") or []:
                if isinstance(m, dict) and isinstance(m.get("id"), str):
                    add(m)
        return header, [msgs[i] for i in order]

    for r in read_rows(path):
        if not isinstance(r, dict):
            continue
        if isinstance(r.get("$rewindTo"), str):
            if r["$rewindTo"] in order:
                for dropped in order[order.index(r["$rewindTo"]):]:
                    msgs.pop(dropped, None)
                del order[order.index(r["$rewindTo"]):]
        elif isinstance(r.get("$patch"), dict):
            _apply_patch(order, msgs, r["$patch"])
        elif isinstance(r.get("$set"), dict):
            for k, v in r["$set"].items():
                if k == "messages":  # an old full-history checkpoint
                    order.clear()
                    msgs.clear()
                    for m in v or []:
                        if isinstance(m, dict) and isinstance(m.get("id"), str):
                            add(m)
                else:
                    header[k] = v
        elif isinstance(r.get("id"), str) and "timestamp" in r:
            add(r)
        elif "sessionId" in r and "projectHash" in r:
            header.update(r)
    return header, [msgs[i] for i in order]


def _ms(a: Optional[str], b: Optional[str]) -> Optional[float]:
    def t(x: Optional[str]) -> Optional[float]:
        try:
            return datetime.fromisoformat(x.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp() if x else None
        except ValueError:
            return None
    ta, tb = t(a), t(b)
    return max(0.0, (tb - ta) * 1000) if ta is not None and tb is not None else None


def parse(path: str) -> ParsedSession:
    stat = os.stat(path)
    header, messages = load(path)
    stem = os.path.basename(path).rsplit(".json", 1)[0]
    meta = SessionMeta(id=str(header.get("sessionId") or stem), agent=AGENT, path=path, size_bytes=stat.st_size,
                       fidelity="estimated", project=_project_of(path))
    meta.started_at = header.get("startTime")
    meta.ended_at = header.get("lastUpdated") or meta.started_at
    ps = ParsedSession(meta=meta)

    turn = 0
    first_prompt = ""
    models_seen: list[str] = []
    search: list[str] = []
    search_len = 0
    last_ts: Optional[str] = meta.started_at

    def add(kind: str, ts: Optional[str], text: str = "", **kw: Any) -> Event:
        ev = Event(idx=len(ps.events), kind=kind, ts=ts, turn=turn, text=_clip(text), **kw)
        ps.events.append(ev)
        return ev

    def remember(text: str) -> None:
        nonlocal search_len
        if search_len < SEARCH_TEXT_CAP and text:
            search.append(text)
            search_len += len(text)

    for m in messages:
        kind = m.get("type")
        ts = m.get("timestamp")
        text = _text_of(m.get("content"))
        if kind == "user":
            if not text.strip():
                continue
            ev_kind, label = classify_text(text)
            if ev_kind == M.CONTEXT:
                add(M.CONTEXT, ts, text, label=label)
            else:
                turn += 1
                first_prompt = first_prompt or text
                remember(text)
                add(M.USER, ts, text)
            last_ts = ts
        elif kind == "gemini":
            model = m.get("model") or "unknown"
            tokens = m.get("tokens") if isinstance(m.get("tokens"), dict) else None
            first = len(ps.events)
            for th in m.get("thoughts") or []:
                if isinstance(th, dict):
                    body = " — ".join(x for x in (th.get("subject"), th.get("description")) if x)
                    add(M.THINKING, th.get("timestamp") or ts, body, model=model)
            if text.strip():
                remember(text)
                add(M.ASSISTANT, ts, text, model=model)
            calls = [c for c in m.get("toolCalls") or [] if isinstance(c, dict)]
            for c in calls:
                add(M.TOOL_CALL, c.get("timestamp") or ts, "", tool_name=c.get("name"), tool_input=c.get("args"),
                    tool_use_id=c.get("id"), model=model)
                add(M.TOOL_RESULT, c.get("timestamp") or ts, _result_text(c), tool_use_id=c.get("id"),
                    is_error=c.get("status") in ("error", "cancelled"))
            if tokens:
                cached = int(tokens.get("cached") or 0)
                prompt = int(tokens.get("input") or 0) + int(tokens.get("tool") or 0)
                step = Step(
                    index=len(ps.steps), turn=turn, model=model, ts=last_ts, end_ts=ts, msg_id=m.get("id"),
                    input_tokens=max(0, prompt - cached), cache_read_tokens=cached,
                    output_tokens=int(tokens.get("output") or 0) + int(tokens.get("thoughts") or 0),
                    request_ts=last_ts, first_event=first, system_key=None,
                )
                step.model_ms = _ms(last_ts, ts)
                ps.steps.append(step)
                for ev in ps.events[first:]:
                    ev.step = step.index
                if model not in models_seen:
                    models_seen.append(model)
            last_ts = ts
        elif kind in ("error", "warning") and text.strip():
            add(M.SYSTEM_EVENT, ts, text, label=kind)

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
    title = str(header.get("summary") or first_prompt).strip()
    meta.title = ((title.splitlines()[0] if title else "") or meta.id)[:200]
    ps.search_text = "\n".join(search)[:SEARCH_TEXT_CAP]
    return ps
