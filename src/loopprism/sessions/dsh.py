"""DeepSeek Harness (``dsh``) adapter: ``~/.dsh/sessions/<project>/<session>/session[.vN].jsonl[.zstd]``.

A session is an append-only event log. Files are usually zstd-compressed as a series of
independent frames (one per flush), so a file being written can end in a half frame; that
tail is left for the next scan. The log has two layers:

* the *surface* the human saw (``surfaceOp: "append"``), which keeps every message and the
  full tool output; and
* *replacements* (``surfaceOp: {"op": "replace", ...}``) that only change what the model sees
  (a compaction summary, a trimmed tool output). Those are skipped here, except that a
  replacement user message marks a compaction.

Streaming chunk events are ignored; the finished ``assistant/message`` carries the content and
the token usage of one model call.
"""

from __future__ import annotations

import json
import os
import sys
import re
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

from ..cost.pricing import usage_cost
from . import models as M
from .claude_code import _clip
from .models import Event, ParsedSession, SessionMeta, Step

AGENT = "dsh"
MAX_BYTES = 256 * 1024 * 1024  # decompressed size we are willing to hold in memory
SEARCH_TEXT_CAP = 150_000
FILE_RE = re.compile(r"^session(?:\.v(\d+))?\.jsonl(\.zstd)?$")
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


class ZstdUnavailable(RuntimeError):
    pass


def dsh_root() -> str:
    base = os.environ.get("DSH_HOME") or os.path.join(os.path.expanduser("~"), ".dsh")
    return os.path.join(base, "sessions")


def desktop_root() -> str:
    """DSH Desktop keeps its own copy of the harness (and its sessions) in its app-data folder."""
    base = os.environ.get("DSH_DESKTOP_HOME")
    if not base:
        if sys.platform == "darwin":
            base = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "dsh-desktop", "harness")
        elif sys.platform == "win32":
            base = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "dsh-desktop", "harness")
        else:
            return ""
    return os.path.join(base, "sessions")


# ------------------------------------------------------------------ discovery
def discover(root: str) -> list[str]:
    """The current log of every session: ``<project>/<session>/session.vN.jsonl[.zstd]``.

    A session directory can hold several generations; only the newest is the live one. Older
    versions wrote a plain ``session.jsonl[.zstd]``, which counts as generation 0.
    """
    found: list[str] = []
    if not os.path.isdir(root):
        return found
    for project in os.scandir(root):
        if not project.is_dir(follow_symlinks=False):
            continue
        for session in os.scandir(project.path):
            if not session.is_dir(follow_symlinks=False):
                continue
            best: Optional[tuple[int, str]] = None
            for f in os.scandir(session.path):
                m = FILE_RE.match(f.name)
                if m and f.is_file(follow_symlinks=False):
                    key = (int(m.group(1) or 0), f.name)
                    if best is None or key > best:
                        best = key
            if best:
                found.append(os.path.join(session.path, best[1]))
    return found


# -------------------------------------------------------------------- reading
def _decoder():
    """A zstd decoder factory: the stdlib module on Python 3.14+, else the ``zstandard`` package."""
    try:
        from compression import zstd  # type: ignore[import-not-found]

        return lambda: zstd.ZstdDecompressor()
    except ImportError:
        pass
    try:
        import zstandard
    except ImportError as err:  # pragma: no cover - a declared dependency
        raise ZstdUnavailable("Reading DeepSeek Harness sessions needs the 'zstandard' package") from err
    return lambda: zstandard.ZstdDecompressor().decompressobj()


def decompress(data: bytes) -> bytes:
    """Decompress concatenated zstd frames, stopping quietly at an unfinished last frame."""
    make = _decoder()
    out: list[bytes] = []
    size = 0
    rest = data
    while rest:
        if len(rest) < 4 and ZSTD_MAGIC.startswith(rest):
            break  # the start of a frame that is still being written
        dec = make()
        try:
            chunk = dec.decompress(rest)
        except Exception as err:  # a corrupt frame in the middle is an error, a cut one is not
            if out and not getattr(dec, "eof", False):
                break
            raise ValueError(f"not a valid zstd session: {err}") from err
        if not getattr(dec, "eof", False):
            break  # truncated final frame: what it held so far is unreliable, wait for the next scan
        out.append(chunk)
        size += len(chunk)
        if size > MAX_BYTES:
            raise ValueError("DeepSeek Harness session is too large")
        rest = getattr(dec, "unused_data", b"") or b""
    return b"".join(out)


def read_session(path: str) -> bytes:
    with open(path, "rb") as fh:
        data = fh.read()
    return decompress(data) if path.endswith(".zstd") else data


def read_records(path: str) -> Iterator[dict[str, Any]]:
    """Complete JSONL lines only: a line without its newline is still being written."""
    lines = read_session(path).split(b"\n")
    lines.pop()  # after the last newline: empty, or a line that is still being written
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            yield row


# -------------------------------------------------------------------- parsing
def _iso(ms: Any) -> Optional[str]:
    if not isinstance(ms, (int, float)):
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(ms) % 1000:03d}Z"


def _ms(a: Any, b: Any) -> Optional[float]:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return max(0.0, float(b) - float(a))
    return None


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for p in content or []:
        if isinstance(p, dict):
            t = p.get("text")
            parts.append(t if isinstance(t, str) else f"[{p.get('type', 'block')}]")
    return "\n".join(x for x in parts if x)


def _maybe_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _result_of(message: dict[str, Any]) -> tuple[Optional[str], str, bool]:
    """(call id, text, is_error) of a ``tool/result`` message, in either of the shapes dsh wrote."""
    call_id = message.get("toolCallId") or (message.get("source") or {}).get("callId")
    is_error = bool(message.get("isError"))
    texts: list[str] = []
    for part in message.get("content") or []:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "tool-result":
            call_id = call_id or part.get("toolCallId")
            is_error = is_error or bool(part.get("isError"))
            texts.append(_text_of(part.get("content")))
        else:
            texts.append(_text_of([part]))
    return call_id, "\n".join(t for t in texts if t), is_error


def parse(path: str) -> ParsedSession:
    stat = os.stat(path)
    session_dir = os.path.basename(os.path.dirname(path))
    meta = SessionMeta(id=session_dir, agent=AGENT, path=path, size_bytes=stat.st_size, fidelity="exact")
    ps = ParsedSession(meta=meta)

    turn = 0
    first_prompt = ""
    title = ""
    window: Optional[int] = None
    models_seen: list[str] = []
    seen_ids: set[str] = set()
    search: list[str] = []
    search_len = 0
    last_input_ms: Optional[float] = None
    step_start_ms: dict[Any, float] = {}
    call_ms: dict[str, float] = {}
    call_step: dict[str, Step] = {}
    system_text = ""
    tools_schema: list[Any] = []

    def add(kind: str, ms: Any, text: str = "", **kw: Any) -> Event:
        ev = Event(idx=len(ps.events), kind=kind, ts=_iso(ms), turn=turn, text=_clip(text), **kw)
        ps.events.append(ev)
        return ev

    def remember(text: str) -> None:
        nonlocal search_len
        if search_len < SEARCH_TEXT_CAP and text:
            search.append(text)
            search_len += len(text)

    last_ms: Any = None
    for r in read_records(path):
        t = r.get("type")
        d = r.get("data") if isinstance(r.get("data"), dict) else {}
        ms = r.get("time")
        if t in ("session", "header") and "id" in r:
            meta.id = str(r["id"]) or meta.id
            meta.project = r.get("cwd") or meta.project
            meta.started_at = _iso(r.get("createdAt")) or meta.started_at
            if r.get("version") is not None:
                meta.version = f"v{r['version']}"
            continue
        if isinstance(ms, (int, float)):
            last_ms = ms
            meta.started_at = meta.started_at or _iso(ms)
        op = r.get("surfaceOp")
        replacement = isinstance(op, dict) and op.get("op") == "replace"

        if t == "request/context":
            window = d.get("contextWindow") or window
        elif t == "request/header":
            header = d.get("header") or {}
            if isinstance(header.get("system"), str) and header["system"]:
                system_text = header["system"]
            if isinstance(header.get("tools"), list) and header["tools"]:
                tools_schema = header["tools"]
        elif t == "session/title":
            title = str(d.get("title") or title)
        elif t == "step/start":
            step_start_ms[d.get("step")] = ms
        elif t == "user/message":
            if replacement:
                # a replacement user message is the model-visible compaction summary
                add(M.COMPACTION, ms, _text_of(d.get("content")), label="summary")
                continue
            mid = d.get("id")
            if mid:
                if mid in seen_ids:
                    continue
                seen_ids.add(mid)
            text = _text_of(d.get("content"))
            if not text.strip():
                continue
            source = d.get("source") or {}
            if source.get("kind") not in (None, "user"):
                add(M.CONTEXT, ms, text, label=str(source.get("plugin") or source.get("kind")))
            else:
                turn += 1
                first_prompt = first_prompt or text
                remember(text)
                add(M.USER, ms, text)
            last_input_ms = ms
        elif t == "assistant/message":
            if replacement:
                continue
            msg = d.get("message") or {}
            mid = msg.get("id")
            if mid:
                if mid in seen_ids:
                    continue
                seen_ids.add(mid)
            model = (msg.get("source") or {}).get("model") or "unknown"
            first = len(ps.events)
            created: list[Event] = []
            for part in msg.get("content") or []:
                if not isinstance(part, dict):
                    continue
                pt = part.get("type")
                if pt == "text" and isinstance(part.get("text"), str) and part["text"].strip():
                    remember(part["text"])
                    created.append(add(M.ASSISTANT, ms, part["text"]))
                elif pt in ("reasoning", "thinking"):
                    created.append(add(M.THINKING, ms, str(part.get("text") or part.get("thinking") or "")))
                elif pt == "tool-call":
                    ev = add(M.TOOL_CALL, ms, "", tool_name=part.get("name"), tool_input=_maybe_json(part.get("arguments")),
                             tool_use_id=part.get("id"))
                    created.append(ev)
            usage = d.get("usage") or {}
            if usage:
                cache_read = int(usage.get("cacheReadTokens") or 0)
                cache_write = int(usage.get("cacheWriteTokens") or 0)
                step = Step(
                    index=len(ps.steps),
                    turn=turn,
                    model=model,
                    ts=_iso(step_start_ms.get(d.get("step")) or last_input_ms),
                    end_ts=_iso(ms),
                    msg_id=mid,
                    input_tokens=int(usage.get("inputTokens") or 0),  # dsh reports uncached input
                    output_tokens=int(usage.get("outputTokens") or 0),
                    cache_read_tokens=cache_read,
                    cache_write_tokens=cache_write,
                    request_ts=_iso(last_input_ms),
                    first_event=first,
                    system_key=AGENT,
                    context_window=int(window) if window else None,
                )
                step.model_ms = _ms(step_start_ms.get(d.get("step")) or last_input_ms, ms)
                ps.steps.append(step)
                for ev in created:
                    ev.step = step.index
                    ev.model = model
                    if ev.kind == M.TOOL_CALL and ev.tool_use_id:
                        call_step[ev.tool_use_id] = step
                if model not in models_seen:
                    models_seen.append(model)
        elif t == "tool/call":
            if d.get("callId"):
                call_ms[d["callId"]] = ms
        elif t == "tool/result":
            if replacement:
                continue
            call_id, text, is_error = _result_of(d.get("message") or {})
            add(M.TOOL_RESULT, ms, text, tool_use_id=call_id, is_error=is_error)
            last_input_ms = ms
            st = call_step.get(call_id or "")
            took = _ms(call_ms.get(call_id or ""), ms)
            if st is not None and took is not None:
                st.tools_ms = max(st.tools_ms or 0.0, took)

    meta.ended_at = _iso(last_ms) or meta.started_at
    ps.shapes[AGENT] = {
        "system": [{"type": "text", "text": system_text}] if system_text else [],
        "tools": tools_schema,
    }
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
