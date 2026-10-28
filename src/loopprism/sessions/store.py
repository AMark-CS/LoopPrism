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

from . import claude_code, codex
from .models import ParsedSession, SessionMeta

CACHE_SIZE = 4


def claude_root() -> str:
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(Path.home(), ".claude")
    return os.path.join(base, "projects")


def codex_root() -> str:
    base = os.environ.get("CODEX_HOME") or os.path.join(Path.home(), ".codex")
    return os.path.join(base, "sessions")


class SessionStore:
    def __init__(self, index_path: Optional[str] = None, roots: Optional[dict[str, str]] = None) -> None:
        self.roots = roots if roots is not None else {"claude-code": claude_root(), "codex": codex_root()}
        self._lock = threading.RLock()
        self._cache: "OrderedDict[str, tuple[tuple[float, int], ParsedSession]]" = OrderedDict()
        if index_path:
            os.makedirs(os.path.dirname(index_path), exist_ok=True)
        self._db = sqlite3.connect(index_path or ":memory:", check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._fts = True
        self._init_db()
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
                CREATE INDEX IF NOT EXISTS idx_sessions_id ON sessions(id);
                CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at);
                """
            )
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
        return found

    @staticmethod
    def _parser(agent: str):
        return claude_code if agent == "claude-code" else codex

    def _index_file(self, path: str, agent: str) -> None:
        st = os.stat(path)
        ps = self._parser(agent).parse(path)
        m = ps.meta
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (path, st.st_mtime, st.st_size, m.agent, m.id, m.project, m.title, m.started_at, m.ended_at,
                 json.dumps(m.models), m.turns, m.steps, m.messages, m.tool_calls, m.cost_usd, m.fidelity,
                 m.version, m.subagent_steps, m.git_branch),
            )
            self._db.execute("DELETE FROM fts WHERE path = ?", (path,))
            self._db.execute("INSERT INTO fts (path, title, body) VALUES (?,?,?)", (path, m.title, ps.search_text))
            self._db.commit()
        self._remember(path, (st.st_mtime, st.st_size), ps)

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
            self._db.commit()
        todo = []
        for path, agent in files:
            try:
                st = os.stat(path)
            except OSError:
                continue
            if known.get(path) != (st.st_mtime, st.st_size):
                todo.append((st.st_mtime, path, agent))
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
            st = os.stat(path)
        except OSError:
            return None
        sig = (st.st_mtime, st.st_size)
        with self._lock:
            hit = self._cache.get(path)
            if hit and hit[0] == sig:
                self._cache.move_to_end(path)
                return hit[1]
        ps = self._parser(row["agent"]).parse(path)
        self._remember(path, sig, ps)
        return ps

    def forget(self, path: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM sessions WHERE path = ?", (path,))
            self._db.execute("DELETE FROM fts WHERE path = ?", (path,))
            self._db.commit()
            self._cache.pop(path, None)

    def allowed_roots(self) -> list[str]:
        return [r for r in self.roots.values() if r]
