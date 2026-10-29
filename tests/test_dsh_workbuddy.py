"""DeepSeek Harness and WorkBuddy session adapters, on made-up sessions in their native formats."""

import os

import pytest
import zstandard
from httpx import ASGITransport, AsyncClient

from loopprism.api.app import create_app
from loopprism.sessions import context, dsh, opencode, workbuddy
from loopprism.sessions.store import SessionStore

from tests.support_other_agents import dsh_rows, frames, jl, wb_rows, write_opencode  # noqa: E402


@pytest.fixture
def dsh_home(tmp_path, monkeypatch):
    root = tmp_path / ".dsh"
    monkeypatch.setenv("DSH_HOME", str(root))
    d = root / "sessions" / "--work-app--" / "session-abc"
    d.mkdir(parents=True)
    (d / "session.v4.jsonl.zstd").write_bytes(frames(dsh_rows()))
    return root


class TestDshDesktop:
    def test_sessions_of_dsh_desktop_are_read_too(self, tmp_path, monkeypatch, dsh_home):
        from loopprism.sessions.store import SessionStore

        desk = tmp_path / "desk"
        monkeypatch.setenv("DSH_DESKTOP_HOME", str(desk))
        d = desk / "sessions" / "--work-desktop--" / "session-desk"
        d.mkdir(parents=True)
        (d / "session.v4.jsonl.zstd").write_bytes(frames(dsh_rows()))
        assert dsh.desktop_root() == str(desk / "sessions")
        store = SessionStore(index_path=str(tmp_path / "idx.db"))
        store.refresh(5)
        rows = [r for r in store.list() if r["agent"] == "dsh"]
        assert len(rows) == 2  # the CLI's and the Desktop's


class TestDshFiles:
    def test_discover_takes_the_newest_generation_of_each_session(self, tmp_path):
        s1 = tmp_path / "p" / "s1"
        s2 = tmp_path / "p" / "s2"
        s3 = tmp_path / "p" / "s3"
        for d in (s1, s2, s3):
            d.mkdir(parents=True)
        for name in ("session.v2.jsonl.zstd", "session.v10.jsonl.zstd", "session.v9.jsonl", "notes.txt"):
            (s1 / name).write_bytes(b"")
        (s2 / "session.jsonl.zstd").write_bytes(b"")  # older dsh versions: no generation in the name
        (tmp_path / "p" / "loose.jsonl").write_bytes(b"")
        found = sorted(os.path.relpath(p, tmp_path) for p in dsh.discover(str(tmp_path)))
        assert found == sorted([os.path.join("p", "s1", "session.v10.jsonl.zstd"), os.path.join("p", "s2", "session.jsonl.zstd")])

    def test_concatenated_frames_and_a_half_written_tail(self):
        rows = [{"n": i} for i in range(7)]
        full = frames(rows, per_frame=2)
        assert dsh.decompress(full) == jl(rows).encode()
        extra = zstandard.ZstdCompressor().compress(b'{"n": 99}\n')
        assert dsh.decompress(full + extra[: len(extra) // 2]) == jl(rows).encode()  # cut in the middle of a frame
        assert dsh.decompress(full + extra[:2]) == jl(rows).encode()  # cut inside the magic number
        with pytest.raises(ValueError):
            dsh.decompress(b"definitely not zstd")

    def test_plain_jsonl_with_an_unfinished_line(self, tmp_path):
        p = tmp_path / "session.jsonl"
        p.write_bytes(jl([{"a": 1}, {"a": 2}]).encode() + b'{"a": 3')
        assert [r["a"] for r in dsh.read_records(str(p))] == [1, 2]


class TestDshParse:
    def parse(self, dsh_home):
        (path,) = dsh.discover(dsh.dsh_root())
        return dsh.parse(path)

    def test_meta_and_counts(self, dsh_home):
        ps = self.parse(dsh_home)
        m = ps.meta
        assert (m.id, m.agent, m.project, m.title) == ("session-abc", "dsh", "/work/app", "Parser fix")
        assert (m.turns, m.steps, m.tool_calls, m.fidelity, m.version) == (1, 2, 1, "exact", "v4")
        assert m.models == ["deepseek-v4-flash"]
        assert m.started_at == "2026-08-17T13:55:41.000Z"
        assert m.cost_usd > 0  # priced with the DeepSeek family price (uncached 900 + cached 10800 in, 70 out)

    def test_events_skip_replacements_and_duplicates(self, dsh_home):
        ps = self.parse(dsh_home)
        assert [(e.kind, e.step) for e in ps.events] == [
            ("context", None), ("user", None), ("thinking", 0), ("assistant", 0), ("tool_call", 0),
            ("tool_result", None), ("assistant", 1), ("compaction", None),
        ]
        ctx = ps.events[0]
        assert ctx.label == "user-approval"
        call = next(e for e in ps.events if e.kind == "tool_call")
        assert (call.tool_name, call.tool_use_id, call.tool_input) == ("bash", "call1", {"command": "cat parser.py"})
        result = next(e for e in ps.events if e.kind == "tool_result")
        assert (result.text, result.tool_use_id, result.is_error) == ("def parse(): pass", "call1", False)  # not "trimmed"
        assert ps.events[-1].label == "summary"  # the compaction summary resets the context estimate

    def test_usage_timing_and_window(self, dsh_home):
        s0, s1 = self.parse(dsh_home).steps
        # dsh reports uncached input; the cache read is separate
        assert (s0.input_tokens, s0.cache_read_tokens, s0.output_tokens, s0.total_input) == (800, 5000, 60, 5800)
        assert s0.context_window == 1_000_000
        assert s0.model_ms == 3000.0  # step/start to the finished message
        assert s0.tools_ms == 1000.0  # tool call to its result
        assert (s1.input_tokens, s1.cache_read_tokens) == (100, 5800)

    def test_the_request_is_recorded_so_the_context_is_exact(self, dsh_home):
        ps = self.parse(dsh_home)
        c = context.step_context(ps, 1, detail=True)
        by_key = {x["key"]: x for x in c["categories"]}
        assert by_key["system_prompt"]["tokens"] > 0 and by_key["tool_schemas"]["items"] == 1
        assert "unattributed" not in by_key  # system prompt and tools are known, nothing is inferred
        assert c["window"] == 1_000_000 and c["window_source"] == "reported"


# ------------------------------------------------------------------ WorkBuddy
@pytest.fixture
def wb_home(tmp_path, monkeypatch):
    root = tmp_path / ".workbuddy"
    monkeypatch.setenv("WORKBUDDY_CONFIG_DIR", str(root))
    d = root / "projects" / "Users-demo-app"
    d.mkdir(parents=True)
    (d / "s-1.jsonl").write_text(jl(wb_rows()))
    (d / "notes.txt").write_text("not a transcript")
    return root


class TestWorkBuddy:
    def parse(self, wb_home):
        (path,) = workbuddy.discover(workbuddy.workbuddy_root())
        return workbuddy.parse(path)

    def test_meta_and_counts(self, wb_home):
        m = self.parse(wb_home).meta
        assert (m.id, m.agent, m.project, m.title, m.fidelity) == ("s-1", "workbuddy", "/work/app", "Parser fix", "estimated")
        assert (m.turns, m.steps, m.tool_calls) == (1, 2, 2)
        assert m.models == ["deepseek-v4.1-flash"]

    def test_one_step_per_response_with_the_cached_part_split_out(self, wb_home):
        s0, s1 = self.parse(wb_home).steps
        # prompt_tokens includes the cached part
        assert (s0.input_tokens, s0.cache_read_tokens, s0.output_tokens, s0.total_input) == (200, 800, 50, 1000)
        assert (s1.input_tokens, s1.cache_read_tokens, s1.output_tokens) == (100, 1400, 30)
        assert s0.tools_ms == 1099.0 and s0.model_ms == 2200.0  # slowest tool; request to the response's usage

    def test_events(self, wb_home):
        ps = self.parse(wb_home)
        assert [(e.kind, e.step) for e in ps.events] == [
            ("context", None), ("user", None), ("thinking", 0), ("assistant", 0), ("tool_call", 0), ("tool_call", 0),
            ("tool_result", None), ("tool_result", None), ("assistant", 1), ("system_event", None), ("compaction", None),
        ]
        calls = [e for e in ps.events if e.kind == "tool_call"]
        assert [(c.tool_name, c.tool_use_id) for c in calls] == [("Read", "c1"), ("Bash", "c2")]
        assert calls[0].tool_input == {"file_path": "parser.py"}
        ok, bad = [e for e in ps.events if e.kind == "tool_result"]
        assert (ok.text, ok.is_error, bad.text, bad.is_error) == ("def parse(): pass", False, "boom", True)
        context_event, user_event = ps.events[:2]
        assert (context_event.label, user_event.text) == ("system-reminder", "Fix the parser")  # the prompt, not the reminder
        assert "OS: darwin" in context_event.text
        assert ps.events[2].text == "Look at the file first."
        assert ps.events[-2].label == "error" and ps.events[-1].label == "summary"

    def test_the_context_is_estimated_because_the_request_is_not_recorded(self, wb_home):
        ps = self.parse(wb_home)
        c = context.step_context(ps, 1)
        assert c["exact_request"] is False
        assert {x["key"]: x for x in c["categories"]}["unattributed"]["tokens"] > 0  # system prompt + tools inferred


# ------------------------------------------------------------------- OpenCode
@pytest.fixture
def oc_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    return write_opencode(str(tmp_path))


class TestOpenCode:
    def test_discover_lists_top_level_sessions_only(self, oc_home):
        found = opencode.discover(opencode.opencode_db())
        assert list(found) == [f"{oc_home}#ses_one"]

    def test_parse(self, oc_home):
        ps = opencode.parse(f"{oc_home}#ses_one")
        m = ps.meta
        assert (m.id, m.agent, m.project, m.title, m.fidelity) == ("ses_one", "opencode", "/work/app", "Fix the parser", "estimated")
        assert (m.turns, m.steps, m.tool_calls, m.models, m.version) == (1, 2, 2, ["glm-5.1"], "1.18.0")
        assert [(e.kind, e.step) for e in ps.events] == [
            ("user", None), ("thinking", 0), ("tool_call", 0), ("tool_result", None), ("tool_call", 0),
            ("tool_result", None), ("assistant", 1)]
        s0, s1 = ps.steps
        # tokens.input is uncached; reasoning is billed as output
        assert (s0.input_tokens, s0.output_tokens, s0.cache_read_tokens) == (1000, 70, 4000)
        assert s0.tools_ms == 500.0
        ok, bad = [e for e in ps.events if e.kind == "tool_result"]
        assert (ok.text, ok.is_error, bad.text, bad.is_error) == ("def parse(): pass", False, "exit 1", True)
        assert s0.cost_usd > 0 and s1.cost_usd > 0  # priced from the GLM table, not OpenCode's reported 0 / 0.25

    def test_opencode_reported_cost_is_used_for_models_we_cannot_price(self, oc_home):
        import sqlite3

        c = sqlite3.connect(oc_home)
        c.execute("UPDATE message SET data = replace(data, 'glm-5.1', 'mystery-model-1') WHERE id = 'm2'")
        c.commit()
        c.close()
        s0, s1 = opencode.parse(f"{oc_home}#ses_one").steps
        assert (s0.cost_usd, s1.cost_usd) == (0.0, 0.25)


# ------------------------------------------------------------------- pricing
class TestPricing:
    @pytest.mark.parametrize("model,price", [
        ("deepseek-chat", (0.28, 0.42)), ("Deepseek-V4.1-Flash", (0.28, 0.42)), ("deepseek/deepseek-reasoner", (0.28, 0.42)),
        ("MiniMax-M3", (0.30, 1.20)), ("minimax-m2.7", (0.30, 1.20)),
        ("glm-4.6", (0.60, 2.20)), ("GLM-5.1", (1.00, 3.20)), ("glm-4.5-air", (0.20, 1.10)),
        ("qwen3-max", (1.20, 6.00)), ("qwen3-coder-480b", (1.00, 5.00)), ("qwen3.6-plus", (0.40, 1.20)),
        ("kimi-k2.5", (0.60, 2.50)), ("gemini-3-pro-preview", (2.00, 12.0)),
        ("deepseek-v4-flash-free", (0.0, 0.0)), ("big-pickle", (0.0, 0.0)),
    ])
    def test_models_from_other_vendors_are_priced(self, model, price):
        from loopprism.cost.pricing import lookup

        p = lookup(model)
        assert p is not None and (p.input_cost_per_m, p.output_cost_per_m) == price

    def test_unknown_models_have_no_price(self):
        from loopprism.cost.pricing import lookup

        assert lookup("hy3") is None and lookup("auto") is None and lookup("") is None

    def test_cache_reads_are_cheaper(self):
        from loopprism.cost.pricing import usage_cost

        plain = usage_cost("deepseek-chat", {"input_tokens": 1_000_000})
        cached = usage_cost("deepseek-chat", {"cache_read_tokens": 1_000_000})
        assert plain == pytest.approx(0.28) and cached == pytest.approx(0.028)


# ------------------------------------------------------------- store and API
@pytest.fixture
def both(tmp_path, monkeypatch, dsh_home, wb_home):
    # no Claude Code or Codex data: only the two new agents
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-claude"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "no-codex"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "no-xdg"))
    monkeypatch.setenv("HOME", str(tmp_path))


class TestStoreAndApi:
    def test_cost_overview_adds_up_every_agent(self, both, oc_home):
        store = SessionStore(None)
        store.refresh(5)
        o = store.cost_overview()
        assert set(a["key"] for a in o["by_agent"]) == {"dsh", "workbuddy", "opencode"}
        steps = sum(a["steps"] for a in o["by_agent"])
        assert o["totals"]["steps"] == steps == 6 and o["totals"]["sessions"] == 3
        assert o["by_day"] and o["by_model"] and o["totals"]["cost"] > 0
        assert "hy3" not in o["unpriced_models"]  # not in these fixtures
        assert store.cost_overview(agent="opencode")["totals"]["steps"] == 2
        assert store.cost_overview(since="2999-01-01")["totals"]["steps"] is None  # nothing that late
        assert [t["agent"] for t in o["top_sessions"]][0] in {"dsh", "workbuddy", "opencode"}

    def test_the_store_lists_both_agents_and_searches_them(self, both):
        store = SessionStore(None)
        assert store.refresh(5)["indexed"] == 2
        rows = {r["agent"]: r for r in store.list()}
        assert set(rows) >= {"dsh", "workbuddy"}
        assert rows["dsh"]["read_only"] and rows["workbuddy"]["read_only"]
        assert [r["agent"] for r in store.list(agent="dsh")] == ["dsh"]
        assert store.list(q="parser")  # titles and messages are searchable
        assert store.load("session-abc").meta.agent == "dsh"
        assert store.load("s-1").meta.agent == "workbuddy"

    @pytest.fixture
    async def api(self, collector, both):
        app = create_app(collector=collector, dashboard_enabled=False)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1") as c:
            yield c

    @pytest.mark.asyncio
    async def test_read_only_sessions_open_but_cannot_be_resumed_or_deleted(self, api):
        listed = (await api.get("/api/sessions")).json()
        assert listed["total"] == 2 and all(s["read_only"] for s in listed["sessions"])
        for sid in ("session-abc", "s-1"):
            d = (await api.get(f"/api/sessions/{sid}")).json()
            assert d["session"]["read_only"] is True and d["session"]["resume_command"] is None
            assert (await api.get(f"/api/sessions/{sid}/events")).status_code == 200
            assert (await api.get(f"/api/sessions/{sid}/context")).status_code == 200
            assert (await api.get(f"/api/sessions/{sid}/export.md")).status_code == 200
            assert (await api.post(f"/api/sessions/{sid}/resume")).status_code == 400
            deleted = await api.post(f"/api/sessions/{sid}/delete")
            assert deleted.status_code == 400 and "its own app" in deleted.json()["detail"]
        assert os.path.exists(dsh.discover(dsh.dsh_root())[0])  # nothing was moved
