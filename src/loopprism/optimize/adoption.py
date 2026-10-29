"""Which suggestions the user adopted, and what the spending did afterwards.

Adopting a suggestion stores the date and a baseline (the 14 days before it). Later the same
numbers are measured from the adoption date on and compared. Cost per model call is the main
measure because it does not move when you simply use the agent more or less; cache hit rate is
shown beside it. This is a comparison, not proof: a different kind of work changes it too.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

BASELINE_DAYS = 14
MIN_DAYS_AFTER = 3  # fewer days than this say nothing yet


def _today() -> date:
    return datetime.now(timezone.utc).date()


class Adoptions:
    def __init__(self, db: sqlite3.Connection, lock: threading.RLock) -> None:
        self._db, self._lock = db, lock
        with lock:
            db.execute(
                "CREATE TABLE IF NOT EXISTS adoptions (rule TEXT PRIMARY KEY, state TEXT NOT NULL, at TEXT NOT NULL, baseline TEXT)"
            )
            db.commit()

    # --------------------------------------------------------------- measuring
    def metrics(self, start: str, end: str) -> dict[str, Any]:
        """Spend, calls, cost per call and cache hit rate for the days start..end (inclusive)."""
        with self._lock:
            r = self._db.execute(
                "SELECT SUM(steps) steps, SUM(cost) cost, SUM(priced) priced, SUM(input) input, SUM(cache_read) cache_read, "
                "SUM(cache_write) cache_write, COUNT(DISTINCT day) days FROM usage WHERE day >= ? AND day <= ?",
                (start, end),
            ).fetchone()
        steps, priced = int(r["steps"] or 0), int(r["priced"] or 0)
        total_in = int((r["input"] or 0) + (r["cache_read"] or 0) + (r["cache_write"] or 0))
        cost = float(r["cost"] or 0.0)
        return {
            "start": start, "end": end, "active_days": int(r["days"] or 0), "steps": steps, "spend_usd": round(cost, 4),
            "cost_per_call": round(cost / priced, 6) if priced else None,
            "cache_hit_pct": round(100 * (r["cache_read"] or 0) / total_in, 1) if total_in else None,
        }

    # ------------------------------------------------------------------- state
    def get(self, rule: str) -> Optional[dict[str, Any]]:
        with self._lock:
            r = self._db.execute("SELECT * FROM adoptions WHERE rule = ?", (rule,)).fetchone()
        return dict(r) if r else None

    def states(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM adoptions").fetchall()
        return {r["rule"]: self._present(dict(r)) for r in rows}

    def adopt(self, rule: str) -> dict[str, Any]:
        today = _today()
        base = self.metrics((today - timedelta(days=BASELINE_DAYS)).isoformat(), (today - timedelta(days=1)).isoformat())
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO adoptions VALUES (?,?,?,?)", (rule, "adopted", today.isoformat(), json.dumps(base)))
            self._db.commit()
        return self.states()[rule]

    def dismiss(self, rule: str) -> dict[str, Any]:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO adoptions VALUES (?,?,?,NULL)", (rule, "dismissed", _today().isoformat()))
            self._db.commit()
        return self.states()[rule]

    def reset(self, rule: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM adoptions WHERE rule = ?", (rule,))
            self._db.commit()

    # ------------------------------------------------------------------ result
    def _present(self, row: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {"state": row["state"], "at": row["at"]}
        if row["state"] != "adopted" or not row.get("baseline"):
            return out
        base = json.loads(row["baseline"])
        today = _today()
        days = (today - date.fromisoformat(row["at"])).days
        after = self.metrics(row["at"], today.isoformat())
        out.update({"days_since": days, "before": base, "after": after, "verdict": "waiting"})
        if days < MIN_DAYS_AFTER or after["steps"] < 20:
            out["note"] = f"Too early to tell: wait at least {MIN_DAYS_AFTER} days and some activity."
        elif not base["cost_per_call"] or not after["cost_per_call"] or base["steps"] < 20:
            out["verdict"] = "unknown"
            out["note"] = "Not enough priced activity before the change to compare."
        else:
            change = 100 * (after["cost_per_call"] - base["cost_per_call"]) / base["cost_per_call"]
            out["cost_per_call_change_pct"] = round(change, 1)
            out["verdict"] = "better" if change <= -5 else "worse" if change >= 5 else "same"
            out["note"] = "A comparison of the same measure before and after; a different kind of work moves it too."
        return out
