"""Agent tree: the main agent plus the subagents it spawned (Claude Code)."""

import pytest
from httpx import ASGITransport, AsyncClient

from loopprism.api.app import create_app
from loopprism.sessions import agents, claude_code, codex
from loopprism.sessions.store import SessionStore
from tests import support_agents as S


@pytest.fixture
def session_path(tmp_path):
    return S.write(tmp_path)


@pytest.fixture
def tree(session_path):
    return agents.build(claude_code.parse(session_path))


def by_name(tree):
    return {n["name"]: n for n in tree["agents"]}


class TestTree:
    def test_structure_and_linking(self, tree):
        assert tree["supported"] is True
        n = by_name(tree)
        assert [x["name"] for x in tree["agents"]] == [
            "Main agent", "Map the repo", "Review payments diff", "Write release notes", "Run the tests"]
        assert n["Map the repo"]["parent_id"] == "main" and n["Map the repo"]["id"] == S.A
        assert n["Review payments diff"]["id"] == S.B
        # spawned inside code-review's own transcript, so it is that agent's child
        assert n["Run the tests"]["parent_id"] == S.B and n["Run the tests"]["id"] == S.C
        assert n["Map the repo"]["role"] == "Explore" and n["Review payments diff"]["background"] is True

    def test_each_agent_has_its_own_stats(self, tree):
        n = by_name(tree)
        a, b = n["Map the repo"], n["Review payments diff"]
        assert (a["steps"], a["tool_calls"], a["errors"]) == (2, 1, 0)
        assert (b["steps"], b["tool_calls"], b["errors"]) == (3, 2, 1)  # one Agent spawn + one Read that failed
        assert a["model"] == S.MODEL and a["tokens"]["total"] > 0 and a["cost_usd"] > 0
        assert b["cost_usd"] > a["cost_usd"]
        assert a["tools"] == {"Grep": 1}

    def test_handoffs(self, tree):
        a = by_name(tree)["Map the repo"]
        assert a["task"]["text"] == "Find where payment retries live."
        assert a["result"]["text"] == "Retries are in src/payments/retry.py."
        assert a["task"]["tokens"] > 0 and a["result"]["tokens"] > 0 and a["task"]["estimated"] is True

    def test_notification_supplies_duration_and_status(self, tree):
        b = by_name(tree)["Review payments diff"]
        assert b["duration_ms"] == 188000 and b["status"] == "completed"
        assert by_name(tree)["Map the repo"]["duration_ms"] == 38000  # from timestamps

    def test_spawn_without_an_agent_file_is_still_listed(self, tree):
        d = by_name(tree)["Write release notes"]
        assert d["session_id"] is None and d["status"] == "unknown" and d["steps"] == 0
        assert d["task"]["text"] == "Draft release notes."

    def test_totals(self, tree):
        t = tree["totals"]
        assert t["subagents"] == 4
        assert t["peak_parallel"] == 2  # Explore + code-review, then code-review + test-runner
        subs = [n["cost_usd"] for n in tree["agents"][1:] if n["cost_usd"] is not None]
        assert t["subagent_cost_usd"] == pytest.approx(sum(subs))
        assert t["total_cost_usd"] == pytest.approx(t["main_cost_usd"] + sum(subs))
        assert t["passed_tokens"] > 0

    def test_peak_parallel(self):
        assert agents._peak_parallel([]) == 0
        assert agents._peak_parallel([(0, 10), (5, 15), (12, 20)]) == 2
        assert agents._peak_parallel([(0, 10), (10, 20)]) == 1  # back to back is not parallel

    def test_codex_sessions_are_reported_unsupported(self, session_path):
        ps = claude_code.parse(session_path)
        ps.meta.agent = "codex"
        out = agents.build(ps)
        assert out["supported"] is False and out["agents"] == [] and "Claude Code" in out["reason"]

    def test_session_without_subagents(self, tmp_path):
        S.write(tmp_path)
        import os
        main = os.path.join(str(tmp_path), ".claude", "projects", S.PROJECT, f"{S.SID}.jsonl")
        rows = [l for l in open(main).read().splitlines() if '"name": "Agent"' not in l]
        open(main, "w").write("\n".join(rows) + "\n")
        out = agents.build(claude_code.parse(main))
        assert [n["id"] for n in out["agents"]] == ["main"] and out["totals"]["subagents"] == 0


@pytest.fixture
def home(tmp_path, monkeypatch):
    S.write(tmp_path)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / ".claude"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))
    monkeypatch.setenv("DSH_HOME", str(tmp_path / ".dsh"))
    monkeypatch.setenv("WORKBUDDY_CONFIG_DIR", str(tmp_path / ".workbuddy"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
async def api(collector, home):
    app = create_app(collector=collector, dashboard_enabled=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1") as c:
        yield c


class TestApi:
    @pytest.mark.asyncio
    async def test_list_counts_per_agent(self, api):
        body = (await api.get("/api/sessions")).json()
        assert body["by_agent"] == {"claude-code": body["total"]}
        other = (await api.get("/api/sessions?agent=codex")).json()
        assert other["total"] == 0 and other["by_agent"] == body["by_agent"]

    @pytest.mark.asyncio
    async def test_agents_endpoint(self, api):
        sid = (await api.get("/api/sessions")).json()["sessions"][0]["id"]
        r = await api.get(f"/api/sessions/{sid}/agents")
        assert r.status_code == 200
        body = r.json()
        assert body["totals"]["subagents"] == 4 and body["agents"][0]["id"] == "main"

    @pytest.mark.asyncio
    async def test_subagent_transcript_opens_like_a_session(self, api):
        sid = (await api.get("/api/sessions")).json()["sessions"][0]["id"]
        agent = f"{sid}~{S.A}"
        d = (await api.get(f"/api/sessions/{agent}")).json()
        assert d["session"]["id"] == agent and d["session"]["title"].startswith("Subagent: Find where payment retries")
        assert d["session"]["resume_command"] is None
        # opened on its own, its steps and turn count like any conversation
        assert (d["session"]["turns"], d["session"]["steps"]) == (1, 2) and d["stats"]["steps"] == 2
        ev = (await api.get(f"/api/sessions/{agent}/events", params={"kinds": "assistant"})).json()
        assert ev["events"][-1]["text"] == "Retries are in src/payments/retry.py."
        assert (await api.get(f"/api/sessions/{agent}/context")).status_code == 200

    @pytest.mark.asyncio
    async def test_subagent_ids_are_validated(self, api):
        sid = (await api.get("/api/sessions")).json()["sessions"][0]["id"]
        for bad in (f"{sid}~nosuchagent01", f"{sid}~..", f"{sid}~a/b", f"nope~{S.A}", f"{sid}~"):
            assert (await api.get(f"/api/sessions/{bad}")).status_code == 404, bad

    @pytest.mark.asyncio
    async def test_subagents_cannot_be_resumed_deleted_or_nested(self, api, home):
        sid = (await api.get("/api/sessions")).json()["sessions"][0]["id"]
        agent = f"{sid}~{S.A}"
        assert (await api.post(f"/api/sessions/{agent}/resume")).status_code == 400
        assert (await api.post(f"/api/sessions/{agent}/delete")).status_code == 400
        assert (await api.get(f"/api/sessions/{agent}/agents")).status_code == 400
        import os
        assert os.path.exists(home / ".claude" / "projects" / S.PROJECT / S.SID / "subagents" / f"agent-{S.A}.jsonl")

    @pytest.mark.asyncio
    async def test_foreign_origin_is_refused(self, api):
        sid = (await api.get("/api/sessions")).json()["sessions"][0]["id"]
        r = await api.get(f"/api/sessions/{sid}/agents", headers={"Origin": "https://evil.example"})
        assert r.status_code == 403
