"""Discovery, index and cache of the agents' session files."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Optional

from . import agents, claude_code, codex, dsh, opencode, workbuddy
from . import models as M
from .models import ParsedSession, SessionMeta

CACHE_SIZE = 4
INDEX_VERSION = 3  # bump when what gets indexed changes; the index is rebuilt


def claude_root() -> str:
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(Path.home(), ".claude")
    return os.path.join(base, "projects")


def codex_root() -> str:
    base = os.environ.get("CODEX_HOME") or os.path.join(Path.home(), ".codex")
    return os.path.join(base, "sessions")


# Agents whose sessions are only read: LoopPrism cannot resume or delete them from here.
READ_ONLY_AGENTS = {"dsh", "workbuddy", "opencode"}


def default_roots() -> dict[str, str]:
    return {"claude-code": claude_root(), "codex": codex_root(), "dsh": dsh.dsh_root(), "workbuddy": workbuddy.workbuddy_root(), "opencode": opencode.opencode_db()}


class SessionStore:
    def __init__(self, index_path: Optional[str] = None, roots: Optional[dict[str, str]] = None) -> None:
        self.roots = roots if roots is not None else default_roots()
        self._lock = threading.RLock()
        self._sigs: dict[str, tuple[float, int]] = {}  # OpenCode sessions: signature of each, from discover()
        self._cache: "OrderedDict[str, tuple[tuple[float, int], ParsedSession]]" = OrderedDict()
        if index_path:
            os.makedirs(os.path.dirname(index_path), exist_ok=True)
        self._db = sqlite3.connect(index_path or ":memory:", check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._fts = True
        self._init_db()
        from ..optimize.adoption import Adoptions

        self.adoptions = Adoptions(self._db, self._lock)
        self.pending = 0

    # ---------------------------------------------------------------- schema
    def _init_db(self) -> None:
        with self._lock:
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    path TEXT PRIMARY KEY, mtime REAL, size INTEGER, agent TEXT, id TEXT,
                    project TEXT, title TEXT, started_at TEXT, ended_at TEXT, models TEXT,
                    turns INTEGER, steps INTEGER, messages INTEGER, tool_calls INTEGER,
                    cost_usd REAL, fidelity TEXT, version TEXT, subagent_steps INTEGER,
                    git_branch TEXT
                );
                CREATE TABLE IF NOT EXISTS usage (
                    path TEXT, day TEXT, agent TEXT, project TEXT, model TEXT, steps INTEGER,
                    input INTEGER, output INTEGER, cache_read INTEGER, cache_write INTEGER,
                    cost REAL, priced INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_usage_path ON usage(path);
                CREATE INDEX IF NOT EXISTS idx_usage_day ON usage(day);
                CREATE INDEX IF NOT EXISTS idx_sessions_id ON sessions(id);
                CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at);
                """
            )
            # Rows indexed before ids were made unique per file are rebuilt.
            if self._db.execute("PRAGMA user_version").fetchone()[0] < INDEX_VERSION:
                self._db.execute("DELETE FROM sessions")
                self._db.execute("DELETE FROM usage")
                self._db.execute(f"PRAGMA user_version = {INDEX_VERSION}")
            try:
                self._db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(path UNINDEXED, title, body)")
            except sqlite3.OperationalError:
                self._fts = False
                self._db.execute("CREATE TABLE IF NOT EXISTS fts (path TEXT PRIMARY KEY, title TEXT, body TEXT)")
            self._db.commit()

    # ------------------------------------------------------------- discovery
    def discover(self) -> list[tuple[str, str]]:
        found: list[tuple[str, str]] = []
        root = self.roots.get("claude-code")
        if root and os.path.isdir(root):
            for proj in os.scandir(root):
                if proj.is_dir():
                    for f in os.scandir(proj.path):
                        if f.name.endswith(".jsonl") and f.is_file():
                            found.append((f.path, "claude-code"))
        root = self.roots.get("codex")
        if root and os.path.isdir(root):
            for dirpath, _dirs, files in os.walk(root):
                for name in files:
                    if name.startswith("rollout-") and name.endswith(".jsonl"):
                        found.append((os.path.join(dirpath, name), "codex"))
        if self.roots.get("opencode"):
            self._sigs = opencode.discover(self.roots["opencode"])
            found += [(p, "opencode") for p in self._sigs]
        found += [(p, "dsh") for p in dsh.discover(self.roots["dsh"])] if self.roots.get("dsh") else []
        found += [(p, "workbuddy") for p in workbuddy.discover(self.roots["workbuddy"])] if self.roots.get("workbuddy") else []
        return found

    @staticmethod
    def _parser(agent: str):
        return {"claude-code": claude_code, "codex": codex, "dsh": dsh, "workbuddy": workbuddy, "opencode": opencode}[agent]

    def _sig(self, path: str) -> tuple[float, int]:
        """(mtime, size) that changes when the session does; OpenCode sessions live inside a database."""
        if opencode.SEP in path and path in self._sigs:
            return self._sigs[path]
        st = os.stat(path)
        return (st.st_mtime, st.st_size)

    def _index_file(self, path: str, agent: str) -> None:
        sig = self._sig(path)
        ps = self._parser(agent).parse(path)
        m = ps.meta
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (path, sig[0], sig[1], m.agent, m.id, m.project, m.title, m.started_at, m.ended_at,
                 json.dumps(m.models), m.turns, m.steps, m.messages, m.tool_calls, m.cost_usd, m.fidelity,
                 m.version, m.subagent_steps, m.git_branch),
            )
            self._db.execute("DELETE FROM fts WHERE path = ?", (path,))
            self._db.execute("INSERT INTO fts (path, title, body) VALUES (?,?,?)", (path, m.title, ps.search_text))
            self._db.execute("DELETE FROM usage WHERE path = ?", (path,))
            self._db.executemany("INSERT INTO usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", self._usage_rows(path, ps))
            self._db.commit()
        self._remember(path, sig, ps)

    @staticmethod
    def _usage_rows(path: str, ps: ParsedSession) -> list[tuple]:
        """One row per (day, model) of the session's steps, for the cost overview."""
        agg: dict[tuple[str, str], list[float]] = {}
        for st in ps.steps:
            day = (st.end_ts or st.ts or ps.meta.started_at or "")[:10] or "unknown"
            a = agg.setdefault((day, st.model or "unknown"), [0, 0, 0, 0, 0, 0.0, 0])
            a[0] += 1
            a[1] += st.input_tokens
            a[2] += st.output_tokens
            a[3] += st.cache_read_tokens
            a[4] += st.cache_write_tokens + st.cache_write_1h_tokens
            if st.cost_usd is not None:
                a[5] += st.cost_usd
                a[6] += 1
        m = ps.meta
        return [(path, day, m.agent, m.project, model, int(a[0]), int(a[1]), int(a[2]), int(a[3]), int(a[4]),
                 round(a[5], 6) if a[6] else None, int(a[6])) for (day, model), a in agg.items()]

    def costliest(self, since: Optional[str] = None, agent: Optional[str] = None, limit: int = 80) -> list[dict[str, Any]]:
        """Index rows of the most expensive sessions that started on or after ``since`` (YYYY-MM-DD)."""
        sql, params = "SELECT * FROM sessions WHERE cost_usd IS NOT NULL AND cost_usd > 0", []
        if since:
            sql += " AND substr(started_at, 1, 10) >= ?"
            params.append(since)
        if agent:
            sql += " AND agent = ?"
            params.append(agent)
        with self._lock:
            rows = self._db.execute(sql + " ORDER BY cost_usd DESC LIMIT ?", [*params, limit]).fetchall()
        return [self._row(r) for r in rows]

    def cost_overview(self, since: Optional[str] = None, agent: Optional[str] = None) -> dict[str, Any]:
        """Spend and tokens across every indexed session, by day, model, agent and project."""
        where, params = [], []
        if since:
            where.append("day >= ?")
            params.append(since)
        if agent:
            where.append("agent = ?")
            params.append(agent)
        cond = ("WHERE " + " AND ".join(where)) if where else ""

        def q(group: str) -> list[dict[str, Any]]:
            sql = (f"SELECT {group} AS key, SUM(steps) steps, SUM(input) input, SUM(output) output, "
                   f"SUM(cache_read) cache_read, SUM(cache_write) cache_write, SUM(cost) cost, SUM(priced) priced "
                   f"FROM usage {cond} GROUP BY {group} ORDER BY COALESCE(SUM(cost), 0) DESC, SUM(input + output + cache_read) DESC")
            with self._lock:
                rows = self._db.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

        with self._lock:
            tot = self._db.execute(
                f"SELECT COUNT(DISTINCT path) sessions, SUM(steps) steps, SUM(input) input, SUM(output) output, "
                f"SUM(cache_read) cache_read, SUM(cache_write) cache_write, SUM(cost) cost, SUM(priced) priced FROM usage {cond}",
                params).fetchone()
            top = self._db.execute(
                f"SELECT s.id, s.agent, s.title, s.project, s.started_at, u.cost FROM "
                f"(SELECT path, SUM(cost) cost FROM usage {cond} GROUP BY path HAVING SUM(cost) IS NOT NULL ORDER BY SUM(cost) DESC LIMIT 10) u "
                f"JOIN sessions s ON s.path = u.path ORDER BY u.cost DESC", params).fetchall()
        by_day = sorted(q("day"), key=lambda r: r["key"])
        models = q("model")
        steps, priced = int(tot["steps"] or 0), int(tot["priced"] or 0)
        return {
            "totals": {k: tot[k] for k in tot.keys()} | {"unpriced_steps": steps - priced},
            "by_day": by_day,
            "by_model": models,
            "by_agent": q("agent"),
            "by_project": q("COALESCE(project, '')")[:15],
            "top_sessions": [dict(r) for r in top],
            "unpriced_models": [m["key"] for m in models if m["cost"] is None and (m["input"] or m["output"] or m["cache_read"])],
        }

    def refresh(self, budget_s: float = 2.0) -> dict[str, int]:
        """Index new/changed files (within a time budget) and forget deleted ones."""
        files = self.discover()
        with self._lock:
            known = {r["path"]: (r["mtime"], r["size"]) for r in self._db.execute("SELECT path, mtime, size FROM sessions")}
        live = {p for p, _ in files}
        with self._lock:
            for gone in set(known) - live:
                self._db.execute("DELETE FROM sessions WHERE path = ?", (gone,))
                self._db.execute("DELETE FROM fts WHERE path = ?", (gone,))
                self._db.execute("DELETE FROM usage WHERE path = ?", (gone,))
            self._db.commit()
        todo = []
        for path, agent in files:
            try:
                sig = self._sig(path)
            except OSError:
                continue
            if known.get(path) != sig:
                todo.append((sig[0], path, agent))
        todo.sort(reverse=True)  # newest first
        deadline = time.monotonic() + budget_s
        done = 0
        for _mt, path, agent in todo:
            if time.monotonic() > deadline:
                break
            try:
                self._index_file(path, agent)
            except Exception:  # a broken file must not hide the others
                pass
            done += 1
        self.pending = max(0, len(todo) - done)
        return {"indexed": done, "pending": self.pending, "total": len(files)}

    # ----------------------------------------------------------------- query
    @staticmethod
    def _row(r: sqlite3.Row) -> dict[str, Any]:
        d = dict(r)
        d["models"] = json.loads(d.get("models") or "[]")
        d.pop("mtime", None)
        d["read_only"] = d.get("agent") in READ_ONLY_AGENTS
        return d

    def list(self, agent: Optional[str] = None, q: Optional[str] = None, project: Optional[str] = None,
             limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
        sql = "SELECT s.*"
        params: list[Any] = []
        if q and q.strip():
            terms = [t for t in re.findall(r"\w+", q, flags=re.UNICODE)] or [q.strip()]
            if self._fts:
                match = " ".join(f'"{t}"*' for t in terms)
                sql += ", snippet(fts, 2, '[', ']', '…', 12) AS snippet FROM sessions s JOIN fts ON fts.path = s.path WHERE fts MATCH ?"
                params.append(match)
            else:
                like = f"%{q.strip()}%"
                sql += ", substr(f.body, 1, 160) AS snippet FROM sessions s JOIN fts f ON f.path = s.path WHERE (f.title LIKE ? OR f.body LIKE ?)"
                params += [like, like]
        else:
            sql += " FROM sessions s WHERE 1=1"
        if agent:
            sql += " AND s.agent = ?"
            params.append(agent)
        if project:
            sql += " AND s.project = ?"
            params.append(project)
        sql += " ORDER BY COALESCE(s.ended_at, s.started_at) DESC LIMIT ? OFFSET ?"
        params += [limit, offset]
        with self._lock:
            return [self._row(r) for r in self._db.execute(sql, params)]

    def count(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]

    def projects(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT project, COUNT(*) AS sessions FROM sessions WHERE project IS NOT NULL GROUP BY project ORDER BY MAX(COALESCE(ended_at, started_at)) DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def find(self, session_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            r = self._db.execute("SELECT * FROM sessions WHERE id = ? ORDER BY mtime DESC", (session_id,)).fetchone()
        return self._row(r) | {"path": r["path"]} if r else None

    # ----------------------------------------------------------------- parse
    def _remember(self, path: str, sig: tuple[float, int], ps: ParsedSession) -> None:
        with self._lock:
            self._cache[path] = (sig, ps)
            self._cache.move_to_end(path)
            while len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)

    def load(self, session_id: str) -> Optional[ParsedSession]:
        row = self.find(session_id)
        if row is None:
            return None
        path = row["path"]
        try:
            sig = self._sig(path)
        except OSError:
            return None
        with self._lock:
            hit = self._cache.get(path)
            if hit and hit[0] == sig:
                self._cache.move_to_end(path)
                return hit[1]
        ps = self._parser(row["agent"]).parse(path)
        self._remember(path, sig, ps)
        return ps

    def load_subagent(self, parent_id: str, agent_id: str) -> Optional[ParsedSession]:
        """A subagent's own transcript, addressed as ``<session>~<agent>``."""
        if not agents.AGENT_ID.match(agent_id):
            return None
        row = self.find(parent_id)
        if row is None or row["agent"] != "claude-code":
            return None
        folder = os.path.realpath(agents.subagent_dir(row["path"]))
        path = os.path.realpath(agents.subagent_file(row["path"], agent_id))
        if os.path.dirname(path) != folder or not os.path.isfile(path):
            return None
        st = os.stat(path)
        sig = (st.st_mtime, st.st_size)
        with self._lock:
            hit = self._cache.get(path)
            if hit and hit[0] == sig:
                self._cache.move_to_end(path)
                return hit[1]
        ps = claude_code.parse(path, standalone=True)
        first = next((e.text for e in ps.events if e.kind == M.USER and e.text.strip()), "")
        ps.meta.id = f"{parent_id}~{agent_id}"
        ps.meta.title = ("Subagent: " + (first.strip().splitlines()[0] if first.strip() else agent_id))[:200]
        self._remember(path, sig, ps)
        return ps

    def forget(self, path: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM sessions WHERE path = ?", (path,))
            self._db.execute("DELETE FROM fts WHERE path = ?", (path,))
            self._db.execute("DELETE FROM usage WHERE path = ?", (path,))
            self._db.commit()
            self._cache.pop(path, None)

    def allowed_roots(self) -> list[str]:
        return [r for r in self.roots.values() if r]
