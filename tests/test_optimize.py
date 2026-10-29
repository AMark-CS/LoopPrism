"""Optimize: suggestions with estimated savings, and the adoption comparison."""

from datetime import date, timedelta

import pytest

from loopprism.optimize import analyze
from loopprism.optimize import rules as R
from loopprism.sessions import models as M
from loopprism.sessions.models import Event, ParsedSession, SessionMeta, Step
from loopprism.sessions.store import SessionStore


def session(steps, events=None, sid="s1"):
    ps = ParsedSession(meta=SessionMeta(id=sid, agent="claude-code", path="x"))
    ps.steps = steps
    ps.events = events or []
    return ps


def step(i, model="claude-sonnet-5-5", inp=1000, out=100, read=0, first_event=0, cost=None):
    from loopprism.cost.pricing import usage_cost

    s = Step(index=i, turn=1, model=model, input_tokens=inp, output_tokens=out, cache_read_tokens=read, first_event=first_event)
    s.cost_usd = usage_cost(model, s.usage()) if cost is None else cost
    return s


def call(idx, tool="Bash", inp=None, st=0):
    return Event(idx=idx, kind=M.TOOL_CALL, tool_name=tool, tool_input=inp or {"command": "ls"}, tool_use_id=f"c{idx}", turn=1, step=st)


class TestRules:
    def test_low_cache_hit_prices_the_missing_cache_reads(self):
        steps = [step(i, inp=40_000, read=2_000) for i in range(8)]  # 5% cached
        (f,) = R.low_cache_hit(session(steps))
        assert f.rule == "low_cache_hit" and f.saving > 0.1 and f.confidence == "medium"
        assert R.low_cache_hit(session([step(i, inp=2_000, read=38_000) for i in range(8)])) == []  # already cached
        assert R.low_cache_hit(session(steps[:3])) == []  # too short to build a cache
        assert R.low_cache_hit(session([step(i, model="mystery-model", inp=40_000) for i in range(8)])) == []  # no price

    def test_an_absent_cache_is_flagged_as_possibly_unreported(self):
        (f,) = R.low_cache_hit(session([step(i, model="glm-5.1", inp=60_000) for i in range(8)]))
        assert f.confidence == "low" and "do not report" in f.detail

    def test_cheaper_model_for_a_short_simple_session(self):
        ps = session([step(0, model="claude-opus-5-5", inp=20_000, out=500), step(1, model="claude-opus-5-5", inp=22_000, out=300)])
        (f,) = R.cheaper_model(ps)
        assert f.extra["to"] == "claude-sonnet-5-5" and f.saving > 0.02
        busy = session([step(i, model="claude-opus-5-5", inp=20_000) for i in range(12)])
        assert R.cheaper_model(busy) == []  # long sessions are not "simple"
        assert R.cheaper_model(session([step(0, model="claude-haiku-5-5", inp=20_000)])) == []  # nothing cheaper

    def test_repeated_calls_cost_every_repeat_but_the_first(self):
        steps = [step(i, inp=30_000, read=10_000, first_event=i) for i in range(5)]
        events = [call(i, st=i) for i in range(5)]  # the same Bash call five times
        (f,) = R.repeated_calls(session(steps, events))
        one = steps[1].cost_usd
        assert f.saving == pytest.approx(sum(s.cost_usd for s in steps[1:]), rel=0.5) and f.saving > one

    def test_big_tool_output_is_resent_with_every_later_step(self):
        events = [Event(idx=0, kind=M.TOOL_RESULT, text="x" * 80_000, tool_use_id="c0", turn=1)]
        steps = [step(i, first_event=1) for i in range(30)]
        (f,) = R.big_tool_output(session(steps, events))
        assert f.confidence == "low" and f.saving > 0.02
        assert R.big_tool_output(session(steps, [Event(idx=0, kind=M.TOOL_RESULT, text="short", turn=1)])) == []

    def test_long_session(self):
        steps = [step(i, inp=2_000, read=198_000) for i in range(60)]
        (f,) = R.long_session(session(steps))
        assert f.rule == "long_session" and f.extra["steps"] == 60
        assert R.long_session(session(steps[:20])) == []


class TestAnalyze:
    def test_totals_are_capped_per_session_and_never_exceed_the_spend(self):
        steps = [step(i, model="claude-opus-5-5", inp=40_000, read=1_000, out=200) for i in range(8)]
        ps = session(steps)
        cost = sum(s.cost_usd for s in steps)
        out = analyze([{"id": "s1", "title": "t", "agent": "claude-code", "cost_usd": cost}], lambda sid: ps, cost)
        assert out["suggestions"], "expected at least the cache suggestion"
        assert 0 < out["saving_usd"] <= 0.8 * cost + 1e-9
        assert out["optimized_usd"] == pytest.approx(out["spend_usd"] - out["saving_usd"], abs=1e-4)
        assert out["saving_pct"] == round(100 * out["saving_usd"] / out["spend_usd"], 1)
        top = out["suggestions"][0]
        assert top["evidence"][0]["session_id"] == "s1" and top["how"] and top["id"] in R.COPY

    def test_a_session_that_fails_to_load_or_a_rule_that_crashes_is_skipped(self):
        out = analyze([{"id": "gone", "cost_usd": 1.0}], lambda sid: None, 1.0)
        assert out["suggestions"] == [] and out["saving_usd"] == 0 and out["analyzed_sessions"] == 0
        bad = session([step(0)])
        bad.steps = [None]  # type: ignore[list-item]  # every rule trips over this
        assert analyze([{"id": "s1", "cost_usd": 1.0}], lambda sid: bad, 1.0)["suggestions"] == []


class TestAdoption:
    def usage(self, store, day, steps, cost, cache_read=0, inp=1000):
        store._db.execute("INSERT INTO usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                          ("p", day.isoformat(), "claude-code", None, "m", steps, inp, 10, cache_read, 0, cost, steps))
        store._db.commit()

    def test_adopt_records_a_baseline_and_waits_before_judging(self):
        store = SessionStore(None)
        today = date.today()
        for i in range(1, 8):
            self.usage(store, today - timedelta(days=i), steps=10, cost=1.0)  # 0.10 per call before
        st = store.adoptions.adopt("low_cache_hit")
        assert st["state"] == "adopted" and st["before"]["cost_per_call"] == pytest.approx(0.10)
        assert st["verdict"] == "waiting" and "Too early" in st["note"]

    def test_after_a_few_days_the_same_measure_is_compared(self):
        store = SessionStore(None)
        today = date.today()
        for i in range(1, 8):
            self.usage(store, today - timedelta(days=i), steps=10, cost=1.0)
        store.adoptions.adopt("cheaper_model")
        # pretend it was adopted five days ago, with the activity since then being cheaper per call
        store._db.execute("UPDATE adoptions SET at = ?", ((today - timedelta(days=5)).isoformat(),))
        for i in range(0, 5):
            self.usage(store, today - timedelta(days=i), steps=10, cost=0.5)
        st = store.adoptions.states()["cheaper_model"]
        assert st["verdict"] == "better" and st["cost_per_call_change_pct"] < -5

    def test_dismiss_and_reset(self):
        store = SessionStore(None)
        assert store.adoptions.dismiss("repeated_calls")["state"] == "dismissed"
        store.adoptions.reset("repeated_calls")
        assert store.adoptions.states() == {}
