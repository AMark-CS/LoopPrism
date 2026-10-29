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
        assert 0 < out["saving_usd"] <= 0.8 * cost + 1e-3
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


# ------------------------------------------------------------ tools, settings, AI
class TestTools:
    def repo(self, name, lic="MIT", days=10, archived=False, stars=900):
        from datetime import datetime, timedelta, timezone

        pushed = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        return {"full_name": name, "html_url": f"https://github.com/{name}", "stargazers_count": stars,
                "license": {"spdx_id": lic} if lic else None, "pushed_at": pushed, "description": "d", "archived": archived}

    def test_only_permissive_recent_unarchived_projects_are_listed(self):
        from loopprism.optimize.tools import _entry, acceptable

        ok = lambda **kw: acceptable(_entry(self.repo("a/b", **kw)))  # noqa: E731
        assert ok()
        assert not ok(lic="GPL-3.0-only") and not ok(lic=None) and not ok(lic="NOASSERTION")
        assert not ok(days=400) and not ok(archived=True)

    def test_fetch_uses_the_catalog_then_search_and_skips_bad_ones(self):
        import httpx

        from loopprism.optimize import tools

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path.startswith("/repos/"):
                name = req.url.path.removeprefix("/repos/")
                return httpx.Response(404) if name == "microsoft/LLMLingua" else httpx.Response(200, json=self.repo(name))
            return httpx.Response(200, json={"items": [
                self.repo("x/awesome-claude"), self.repo("x/old", days=999), self.repo("x/gpl", lic="GPL-3.0-only"),
                self.repo("x/good"), self.repo("rtk-ai/rtk")]})  # a catalog repo is not "discovered" again

        found = tools.fetch(httpx.Client(transport=httpx.MockTransport(handler)))
        names = [t["repo"] for t in found]
        assert "microsoft/LLMLingua" not in names  # 404: skipped
        assert names.count("rtk-ai/rtk") == 1 and "x/good" in names
        assert not {"x/awesome-claude", "x/old", "x/gpl"} & set(names)
        assert next(t for t in found if t["repo"] == "x/good")["reviewed"] is False

    def test_the_day_cache_offline_and_the_off_switch(self, tmp_path, monkeypatch):
        from loopprism.optimize import tools

        monkeypatch.setenv("LOOPPRISM_TOOLS_CACHE", str(tmp_path / "c.json"))
        entry = {"repo": "a/b", "url": "u", "stars": 1, "license": "MIT", "pushed_days_ago": 1, "description": "", "archived": False,
                 "tags": ["x"], "kind": "k", "why": "w", "reviewed": True}
        calls = []
        r = tools.tools_for(True, fetcher=lambda: calls.append(1) or [entry])
        assert (r["source"], len(calls)) == ("live", 1)
        assert tools.tools_for(True, fetcher=lambda: calls.append(1) or [])["source"] == "cache" and len(calls) == 1  # once a day
        assert tools.tools_for(True, force=True, fetcher=lambda: calls.append(1) or [])["source"] == "cache"  # offline: last good answer
        monkeypatch.setenv("LOOPPRISM_TOOLS_CACHE", str(tmp_path / "none.json"))
        assert tools.tools_for(False)["source"] == "off"
        offline = tools.tools_for(True, fetcher=lambda: (_ for _ in ()).throw(OSError("offline")))
        assert offline["source"] == "offline" and offline["tools"][0]["reviewed"]  # the reviewed catalog still shows


class TestSettingsAndAi:
    @pytest.fixture(autouse=True)
    def cfg(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOOPPRISM_OPTIMIZE_FILE", str(tmp_path / "o.json"))

    def test_the_key_is_stored_privately_and_never_shown(self, tmp_path):
        import json
        import os
        import sys

        from loopprism.optimize import config as oc

        oc.save({"ai": {"url": "https://api.example.com/v1", "model": "m", "api_key": "sk-secret"}})
        assert "sk-secret" not in json.dumps(oc.public(oc.load())) and oc.public(oc.load())["ai"]["key_set"] is True
        if sys.platform != "win32":
            assert os.stat(tmp_path / "o.json").st_mode & 0o777 == 0o600
        oc.save({"ai": {"model": "m2"}})  # an empty key keeps the stored one
        assert oc.load()["ai"]["api_key"] == "sk-secret"
        oc.save({"ai": {"clear_key": True}})
        assert oc.load()["ai"]["api_key"] == ""

    def test_validation(self):
        from loopprism.optimize import config as oc

        with pytest.raises(ValueError):
            oc.save({"ai": {"url": "http://evil.example.com/v1"}})  # plain http only for this computer
        oc.save({"ai": {"url": "http://localhost:11434/v1"}})
        with pytest.raises(ValueError):
            oc.save({"ai": {"enabled": True}})  # needs url, model and key

    def test_the_request_carries_only_aggregates(self):
        from loopprism.optimize import ai

        overview = {"totals": {"steps": 10, "input": 1, "cache_read": 2, "output": 3},
                    "by_model": [{"key": "glm-5.1", "cost": 1.5, "steps": 10}], "by_agent": [{"key": "opencode", "cost": 1.5}]}
        result = {"days": 30, "spend_usd": 1.5, "saving_usd": 0.4, "saving_pct": 26.7, "suggestions": [
            {"id": "low_cache_hit", "saving_usd": 0.4, "sessions": 1, "confidence": "medium",
             "evidence": [{"session_id": "ses_secret", "title": "My private project", "detail": "glm-5.1: 0% cached"}]}]}
        text = " ".join(m["content"] for m in ai.build_messages(overview, result))
        assert "glm-5.1: 0% cached" in text and "low_cache_hit" in text
        assert "ses_secret" not in text and "private project" not in text
        assert ai.endpoint("https://x/v1/") == "https://x/v1/chat/completions" == ai.endpoint("https://x/v1/chat/completions")

    def test_run_posts_to_the_endpoint_with_the_key(self, monkeypatch):
        import httpx

        from loopprism.optimize import ai

        seen = {}

        def fake_post(url, headers, json, timeout, follow_redirects):
            seen.update(url=url, auth=headers["Authorization"], model=json["model"])
            return httpx.Response(200, json={"choices": [{"message": {"content": " Do X. "}}]}, request=httpx.Request("POST", url))

        monkeypatch.setattr(ai.httpx, "post", fake_post)
        cfg = {"ai": {"url": "https://x/v1", "api_key": "k", "model": "m"}}
        assert ai.run(cfg, [{"role": "user", "content": "hi"}]) == "Do X."
        assert seen == {"url": "https://x/v1/chat/completions", "auth": "Bearer k", "model": "m"}
        monkeypatch.setattr(ai.httpx, "post", lambda *a, **k: httpx.Response(401, text="no", request=httpx.Request("POST", "https://x")))
        with pytest.raises(RuntimeError, match="401"):
            ai.run(cfg, [])


class TestApi:
    @pytest.fixture
    async def api(self, collector, tmp_path, monkeypatch):
        from httpx import ASGITransport, AsyncClient

        from loopprism.api.app import create_app
        from tests.support_other_agents import write, write_opencode

        monkeypatch.setenv("LOOPPRISM_OPTIMIZE_FILE", str(tmp_path / "o.json"))
        monkeypatch.setenv("LOOPPRISM_TOOLS_CACHE", str(tmp_path / "t.json"))
        monkeypatch.setenv("DSH_HOME", str(tmp_path / ".dsh"))
        monkeypatch.setenv("WORKBUDDY_CONFIG_DIR", str(tmp_path / ".workbuddy"))
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no"))
        monkeypatch.setenv("CODEX_HOME", str(tmp_path / "no"))
        write(str(tmp_path))
        write_opencode(str(tmp_path))
        app = create_app(collector=collector, dashboard_enabled=False)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1") as c:
            yield c

    @pytest.mark.asyncio
    async def test_analysis_adoption_settings_and_ai_gate(self, api):
        r = await api.get("/api/sessions/optimize", params={"days": 3650})
        assert r.status_code == 200, r.text
        d = r.json()
        assert set(d) >= {"spend_usd", "saving_usd", "optimized_usd", "saving_pct", "suggestions", "analyzed_sessions"}
        assert d["optimized_usd"] <= d["spend_usd"]
        assert (await api.post("/api/sessions/optimize/nope/adopt")).status_code == 404
        assert (await api.post("/api/sessions/optimize/low_cache_hit/adopt")).json()["state"] == "adopted"
        assert (await api.post("/api/sessions/optimize/low_cache_hit/bogus")).status_code == 400
        assert (await api.post("/api/sessions/optimize/low_cache_hit/reset")).json() == {"state": None}

        s = (await api.get("/api/sessions/optimize/settings")).json()
        assert s["ai"] == {"enabled": False, "url": "", "model": "", "key_set": False} and s["live_tools"] is True
        bad = await api.put("/api/sessions/optimize/settings", json={"ai": {"url": "http://evil.example.com"}})
        assert bad.status_code == 400
        ok = await api.put("/api/sessions/optimize/settings", json={"ai": {"url": "https://api.example.com/v1", "model": "m", "api_key": "sk-1"}})
        assert ok.json()["ai"]["key_set"] is True and "sk-1" not in ok.text
        # preview works and never contains the key; run is refused while AI is off
        pv = (await api.post("/api/sessions/optimize/ai/preview", params={"days": 3650})).json()
        assert pv["ready"] is False and "sk-1" not in str(pv) and pv["messages"][0]["role"] == "system"
        assert (await api.post("/api/sessions/optimize/ai/run", params={"days": 3650})).status_code == 400
        assert (await api.post("/api/sessions/optimize/ai/other")).status_code == 404
