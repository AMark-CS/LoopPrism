"""Cursor adapter: the chats of Cursor's Agent / Chat, kept in ``<Cursor user dir>/globalStorage/state.vscdb``.

The database is VS Code's key-value store (table ``cursorDiskKV``). One conversation ("composer"):

* ``composerData:<id>``: name, times, model, ``workspaceIdentifier`` (a folder id; the folder itself
  is in ``workspaceStorage/<id>/workspace.json``);
* the ordered message list: ``composerConvHeaders:<id>:<chunk>`` (current versions) or
  ``fullConversationHeadersOnly`` inside ``composerData`` (older ones), a list of ``{bubbleId, type}``;
* one ``bubbleId:<id>:<bubble>`` per message: ``type`` 1 is the user's prompt (``text``); ``type`` 2 are the
  agent's steps, stored as ``<bubble>/s:<n>`` (``thinking.text``, ``text``, or a tool call in ``toolFormerData``).

Cursor does not record token usage per message in these records (``tokenCount`` is zero), so Cursor
sessions have no cost; the Cursor hooks (live runs) record prompts and tool calls as they happen.

Sessions are addressed as ``<db>#<composerId>``, like OpenCode's.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import unquote, urlparse

from ..cost.pricing import usage_cost
from . import models as M
from .claude_code import _clip, classify_text
from .models import Event, ParsedSession, SessionMeta, Step

AGENT = "cursor"
SEARCH_TEXT_CAP = 150_000
SEP = "#"
PLACEHOLDER_TITLES = {"", "general chat", "new chat", "new agent", "untitled"}
FAILED = {"error", "failed", "cancelled", "canceled", "rejected", "aborted"}


def user_dir() -> str:
    """Cursor's ``User`` folder (``CURSOR_USER_DIR`` overrides it)."""
    if os.environ.get("CURSOR_USER_DIR"):
        return os.environ["CURSOR_USER_DIR"]
    home = os.path.expanduser("~")
    if sys.platform == "darwin":
        return os.path.join(home, "Library", "Application Support", "Cursor", "User")
    if sys.platform == "win32":
        return os.path.join(os.environ.get("APPDATA") or home, "Cursor", "User")
    return os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config"), "Cursor", "User")


def cursor_db() -> str:
    return os.path.join(user_dir(), "globalStorage", "state.vscdb")


def split_path(path: str) -> tuple[str, str]:
    db, _, cid = path.rpartition(SEP)
    return db, cid


def _connect(db: str) -> sqlite3.Connection:
    uri = "file:" + db.replace("\\", "/").replace("?", "%3f").replace("#", "%23") + "?mode=ro"
    c = sqlite3.connect(uri, uri=True, timeout=2)
    c.row_factory = sqlite3.Row
    return c


def _j(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", "replace")
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def discover(db: str) -> dict[str, tuple[float, int]]:
    """``{<db>#<composer id>: (mtime seconds, size)}`` for every conversation that has messages."""
    out: dict[str, tuple[float, int]] = {}
    if not os.path.isfile(db):
        return out
    try:
        c = _connect(db)
        try:
            counts = {
                r[0]: r[1]
                for r in c.execute(
                    "SELECT substr(key, 10, 36), COUNT(*) FROM cursorDiskKV WHERE key >= 'bubbleId:' AND key < 'bubbleId;' GROUP BY 1"
                )
            }
            skip: set[str] = set()
            try:  # sub-agent conversations are shown inside their parent's, not on their own
                skip = {r[0] for r in c.execute("SELECT composerId FROM composerHeaders WHERE isSubagent = 1")}
            except sqlite3.Error:
                pass
            for r in c.execute("SELECT key, value FROM cursorDiskKV WHERE key LIKE 'composerData:%'"):
                cid = r["key"][len("composerData:"):]
                if cid in skip or not counts.get(cid):
                    continue
                d = _j(r["value"]) or {}
                stamp = d.get("lastUpdatedAt") or d.get("createdAt") or 0
                out[f"{db}{SEP}{cid}"] = (stamp / 1000.0, counts[cid])
        finally:
            c.close()
    except sqlite3.Error:
        return {}
    return out


def _iso(v: Any) -> Optional[str]:
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(v) % 1000:03d}Z"
    return v if isinstance(v, str) else None


def _folder_of(db: str, workspace_id: Optional[str]) -> Optional[str]:
    """The project folder of a workspace id, from ``workspaceStorage/<id>/workspace.json``."""
    if not workspace_id or workspace_id == "empty-window":
        return None
    f = os.path.join(os.path.dirname(os.path.dirname(db)), "workspaceStorage", workspace_id, "workspace.json")
    try:
        with open(f, encoding="utf-8") as fh:
            uri = (json.load(fh) or {}).get("folder")
    except (OSError, ValueError):
        return None
    if not isinstance(uri, str):
        return None
    if not uri.startswith("file:"):
        return None  # a remote workspace: keep it out of the project column
    path = unquote(urlparse(uri).path)
    if sys.platform == "win32" and len(path) > 2 and path[0] == "/" and path[2] == ":":
        path = path[1:]
    return path


def _tool_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        v = _j(value)
        if isinstance(v, (dict, list)):
            return json.dumps(v, ensure_ascii=False, indent=2)[:100_000]
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def _ordered_ids(c: sqlite3.Connection, cid: str, header: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    chunks = c.execute(
        "SELECT value FROM cursorDiskKV WHERE key >= ? AND key < ? ORDER BY key",
        (f"composerConvHeaders:{cid}:", f"composerConvHeaders:{cid};"),
    ).fetchall()
    for r in chunks:
        for h in _j(r["value"]) or []:
            if isinstance(h, dict) and h.get("bubbleId"):
                ids.append(h["bubbleId"])
    if not ids:
        for h in header.get("fullConversationHeadersOnly") or []:
            if isinstance(h, dict) and h.get("bubbleId"):
                ids.append(h["bubbleId"])
    return ids


def parse(path: str) -> ParsedSession:
    db, cid = split_path(path)
    st = os.stat(db)
    meta = SessionMeta(id=cid, agent=AGENT, path=path, size_bytes=st.st_size, fidelity="estimated")
    ps = ParsedSession(meta=meta)
    c = _connect(db)
    try:
        row = c.execute("SELECT value FROM cursorDiskKV WHERE key = ?", (f"composerData:{cid}",)).fetchone()
        header = (_j(row["value"]) if row else None) or {}
        ids = _ordered_ids(c, cid, header)
        bubbles: dict[str, dict[str, Any]] = {}
        for r in c.execute(
            "SELECT key, value FROM cursorDiskKV WHERE key >= ? AND key < ?", (f"bubbleId:{cid}:", f"bubbleId:{cid};")
        ):
            b = _j(r["value"])
            if isinstance(b, dict):
                bubbles[r["key"][len(f"bubbleId:{cid}:"):]] = b
        for b in header.get("conversation") or []:  # the oldest format keeps the messages inside composerData
            if isinstance(b, dict) and b.get("bubbleId"):
                bubbles.setdefault(b["bubbleId"], b)
                if b["bubbleId"] not in ids:
                    ids.append(b["bubbleId"])
    finally:
        c.close()
    if not ids:  # no header list: whatever bubbles there are, in time order
        ids = sorted(bubbles, key=lambda k: str(bubbles[k].get("createdAt") or ""))

    meta.started_at = _iso(header.get("createdAt"))
    meta.ended_at = _iso(header.get("lastUpdatedAt")) or meta.started_at
    ws = (header.get("workspaceIdentifier") or {}).get("id")
    meta.project = _folder_of(db, ws)

    turn = 0
    first_prompt = ""
    models_seen: list[str] = []
    search: list[str] = []
    search_len = 0

    def add(kind: str, ts: Any, text: str = "", **kw: Any) -> Event:
        ev = Event(idx=len(ps.events), kind=kind, ts=_iso(ts), turn=turn, text=_clip(text), **kw)
        ps.events.append(ev)
        return ev

    def remember(text: str) -> None:
        nonlocal search_len
        if search_len < SEARCH_TEXT_CAP and text:
            search.append(text)
            search_len += len(text)

    def see_model(b: dict[str, Any]) -> Optional[str]:
        name = (b.get("modelInfo") or {}).get("modelName") if isinstance(b.get("modelInfo"), dict) else None
        if name and name not in models_seen:
            models_seen.append(name)
        return name

    model = (header.get("modelConfig") or {}).get("modelName") if isinstance(header.get("modelConfig"), dict) else None
    for bid in ids:
        b = bubbles.get(bid)
        if not b:
            continue
        ts = b.get("createdAt")
        model = see_model(b) or model
        text = b.get("text") if isinstance(b.get("text"), str) else ""
        if b.get("type") == 1:
            if not text.strip():
                continue
            kind, label = classify_text(text)
            if kind == M.CONTEXT:
                add(M.CONTEXT, ts, text, label=label)
                continue
            turn += 1
            first_prompt = first_prompt or text
            remember(text)
            add(M.USER, ts, text)
            continue
        thinking = b.get("thinking")
        if isinstance(thinking, dict) and str(thinking.get("text") or "").strip():
            add(M.THINKING, ts, thinking["text"], model=model)
        tool = b.get("toolFormerData")
        if isinstance(tool, dict) and tool.get("name"):
            call_id = str(tool.get("toolCallId") or bid)
            args = _j(tool.get("rawArgs")) if isinstance(tool.get("rawArgs"), str) else tool.get("rawArgs")
            if args is None:
                args = _j(tool.get("params")) if isinstance(tool.get("params"), str) else tool.get("params")
            add(M.TOOL_CALL, ts, "", tool_name=str(tool["name"]), tool_input=args, tool_use_id=call_id, model=model)
            failed = str(tool.get("status") or "").lower() in FAILED
            add(M.TOOL_RESULT, ts, _tool_text(tool.get("result")) or str(tool.get("error") or ""), tool_use_id=call_id,
                is_error=failed)
        if text.strip():
            remember(text)
            add(M.ASSISTANT, ts, text, model=model)
        tokens = b.get("tokenCount") if isinstance(b.get("tokenCount"), dict) else {}
        tin, tout = int(tokens.get("inputTokens") or 0), int(tokens.get("outputTokens") or 0)
        if tin or tout:  # older versions recorded usage per message
            step = Step(index=len(ps.steps), turn=turn, model=model or "unknown", ts=_iso(ts), end_ts=_iso(ts),
                        msg_id=bid, input_tokens=tin, output_tokens=tout, first_event=len(ps.events) - 1)
            ps.steps.append(step)
            ps.events[-1].step = step.index

    total: Optional[float] = None
    for s in ps.steps:
        s.cost_usd = usage_cost(s.model, s.usage())
        if s.cost_usd is not None:
            total = (total or 0.0) + s.cost_usd
    meta.models = models_seen or ([model] if model else [])
    meta.tool_calls = sum(1 for e in ps.events if e.kind == M.TOOL_CALL)
    meta.messages = sum(1 for e in ps.events if e.kind in (M.USER, M.ASSISTANT))
    meta.turns = turn
    meta.steps = len(ps.steps)
    meta.cost_usd = round(total, 6) if total is not None else None
    name = str(header.get("name") or "").strip()
    title = first_prompt.strip() if name.lower() in PLACEHOLDER_TITLES else name
    meta.title = ((title.splitlines()[0] if title else "") or cid)[:200]
    ps.search_text = "\n".join(search)[:SEARCH_TEXT_CAP]
    return ps
