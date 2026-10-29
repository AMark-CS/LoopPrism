"""OpenCode adapter: sessions in ``~/.local/share/opencode/opencode.db`` (SQLite).

Tables used: ``session`` (directory, title, version, model), ``message`` (JSON ``data``: role,
model, tokens) and ``part`` (JSON ``data``: ``text``, ``reasoning``, ``tool``, ``step-start`` /
``step-finish``). A session is not a file, so the store addresses it as ``<db path>#<session id>``.

One assistant message can hold several steps (model calls); each ``step-finish`` part carries the
token usage and OpenCode's own cost of its step. ``tokens.input`` is uncached input, the cache
read/write counts are separate, and ``reasoning`` tokens are billed as output.

OpenCode does not record the system prompt, so the context breakdown is estimated.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

from ..cost.pricing import usage_cost
from . import models as M
from .claude_code import _clip
from .models import Event, ParsedSession, SessionMeta, Step

AGENT = "opencode"
SEARCH_TEXT_CAP = 150_000
SEP = "#"


def opencode_db() -> str:
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "opencode", "opencode.db")


def split_path(path: str) -> tuple[str, str]:
    db, _, sid = path.rpartition(SEP)
    return db, sid


def _connect(db: str) -> sqlite3.Connection:
    uri = "file:" + db.replace("\\", "/").replace("?", "%3f").replace("#", "%23") + "?mode=ro"
    c = sqlite3.connect(uri, uri=True, timeout=2)
    c.row_factory = sqlite3.Row
    return c


def discover(db: str) -> dict[str, tuple[float, int]]:
    """``{<db>#<session id>: (mtime seconds, size)}`` for every top-level session."""
    out: dict[str, tuple[float, int]] = {}
    if not os.path.isfile(db):
        return out
    try:
        c = _connect(db)
        try:
            rows = c.execute(
                "SELECT s.id, s.time_updated, "
                "COALESCE((SELECT MAX(m.time_updated) FROM message m WHERE m.session_id = s.id), 0) AS mu, "
                "(SELECT COUNT(*) FROM part p WHERE p.session_id = s.id) AS parts "
                "FROM session s WHERE s.parent_id IS NULL"
            ).fetchall()
        finally:
            c.close()
    except sqlite3.Error:
        return out
    for r in rows:
        out[f"{db}{SEP}{r['id']}"] = (max(r["time_updated"] or 0, r["mu"] or 0) / 1000.0, int(r["parts"] or 0))
    return out


def _iso(ms: Any) -> Optional[str]:
    if not isinstance(ms, (int, float)):
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(ms) % 1000:03d}Z"


def _ms(a: Any, b: Any) -> Optional[float]:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return max(0.0, float(b) - float(a))
    return None


def _j(text: Any) -> dict[str, Any]:
    try:
        v = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return v if isinstance(v, dict) else {}


def _tool_text(out: Any) -> str:
    if isinstance(out, str):
        return out
    if out is None:
        return ""
    return json.dumps(out, ensure_ascii=False, default=str)


def parse(path: str) -> ParsedSession:
    db, sid = split_path(path)
    st = os.stat(db)
    meta = SessionMeta(id=sid, agent=AGENT, path=path, size_bytes=st.st_size, fidelity="estimated")
    ps = ParsedSession(meta=meta)
    c = _connect(db)
    try:
        srow = c.execute("SELECT * FROM session WHERE id = ?", (sid,)).fetchone()
        messages = c.execute("SELECT id, time_created, data FROM message WHERE session_id = ? ORDER BY time_created, id", (sid,)).fetchall()
        parts: dict[str, list[sqlite3.Row]] = {}
        for p in c.execute("SELECT id, message_id, time_created, data FROM part WHERE session_id = ? ORDER BY time_created, id", (sid,)):
            parts.setdefault(p["message_id"], []).append(p)
    finally:
        c.close()
    if srow is not None:
        meta.project = srow["directory"] or None
        meta.title = srow["title"] or ""
        meta.version = srow["version"]
        meta.started_at = _iso(srow["time_created"])
        meta.ended_at = _iso(srow["time_updated"])

    turn = 0
    first_prompt = ""
    models_seen: list[str] = []
    search: list[str] = []
    search_len = 0
    last_input_ms: Optional[float] = None
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

    for m in messages:
        d = _j(m["data"])
        role = d.get("role")
        ms = m["time_created"]
        last_ms = ms
        if role == "user":
            texts = []
            for p in parts.get(m["id"], []):
                pj = _j(p["data"])
                if pj.get("type") == "text" and isinstance(pj.get("text"), str) and pj["text"].strip():
                    if pj.get("synthetic"):
                        add(M.CONTEXT, ms, pj["text"], label="synthetic")
                    else:
                        texts.append(pj["text"])
            if texts:
                turn += 1
                text = "\n".join(texts)
                first_prompt = first_prompt or text
                remember(text)
                add(M.USER, ms, text)
            last_input_ms = ms
        elif role == "assistant":
            model = d.get("modelID") or "unknown"
            pending: list[int] = []
            tool_ms: dict[str, tuple[Event, float]] = {}
            for p in parts.get(m["id"], []):
                pj = _j(p["data"])
                t = pj.get("type")
                pms = p["time_created"]
                last_ms = pms
                if t == "reasoning":
                    pending.append(add(M.THINKING, (pj.get("time") or {}).get("start") or pms, str(pj.get("text") or "")).idx)
                elif t == "text":
                    text = str(pj.get("text") or "")
                    if text.strip():
                        remember(text)
                        pending.append(add(M.ASSISTANT, (pj.get("time") or {}).get("start") or pms, text).idx)
                elif t == "tool":
                    state = pj.get("state") if isinstance(pj.get("state"), dict) else {}
                    tm = state.get("time") or {}
                    call = add(M.TOOL_CALL, tm.get("start") or pms, "", tool_name=pj.get("tool"), tool_input=state.get("input"),
                               tool_use_id=pj.get("callID"))
                    pending.append(call.idx)
                    if state.get("status") in ("completed", "error"):
                        res = state.get("output") if state.get("status") == "completed" else state.get("error")
                        add(M.TOOL_RESULT, tm.get("end") or pms, _tool_text(res), tool_use_id=pj.get("callID"),
                            is_error=state.get("status") == "error")
                        took = _ms(tm.get("start"), tm.get("end"))
                        if took is not None:
                            tool_ms[pj.get("callID") or ""] = (call, took)
                elif t == "step-finish":
                    tok = pj.get("tokens") or {}
                    cache = tok.get("cache") or {}
                    step = Step(
                        index=len(ps.steps),
                        turn=turn,
                        model=model,
                        ts=_iso(last_input_ms),
                        end_ts=_iso(pms),
                        msg_id=m["id"],
                        input_tokens=int(tok.get("input") or 0),
                        output_tokens=int(tok.get("output") or 0) + int(tok.get("reasoning") or 0),
                        cache_read_tokens=int(cache.get("read") or 0),
                        cache_write_tokens=int(cache.get("write") or 0),
                        request_ts=_iso(last_input_ms),
                        first_event=pending[0] if pending else len(ps.events),
                    )
                    step.model_ms = _ms(last_input_ms, pms)
                    reported = pj.get("cost")
                    ours = usage_cost(model, step.usage())
                    # our price table first (covers the same models in every agent); else what OpenCode charged
                    step.cost_usd = ours if ours is not None else (float(reported) if isinstance(reported, (int, float)) else None)
                    if tool_ms:
                        step.tools_ms = max(v[1] for v in tool_ms.values())
                    for idx in pending:
                        ps.events[idx].step = step.index
                        ps.events[idx].model = model
                    pending = []
                    tool_ms = {}
                    ps.steps.append(step)
                    last_input_ms = pms
                    if model not in models_seen:
                        models_seen.append(model)

    costs = [s.cost_usd for s in ps.steps if s.cost_usd is not None]
    meta.cost_usd = round(sum(costs), 6) if costs else None
    meta.tool_calls = sum(1 for e in ps.events if e.kind == M.TOOL_CALL)
    meta.messages = sum(1 for e in ps.events if e.kind in (M.USER, M.ASSISTANT))
    meta.turns = turn
    meta.steps = len(ps.steps)
    meta.models = models_seen
    meta.ended_at = _iso(last_ms) or meta.ended_at
    if not meta.title or meta.title.startswith("New session"):
        line = first_prompt.strip().splitlines()[0] if first_prompt.strip() else ""
        meta.title = (line or meta.title or sid)[:200]
    ps.search_text = "\n".join(search)[:SEARCH_TEXT_CAP]
    return ps
