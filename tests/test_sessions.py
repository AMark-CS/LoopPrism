"""Tests for the session inspector: parsers, context breakdown, store and API."""

import json
import os

import pytest
from httpx import ASGITransport, AsyncClient

from loopprism.api.app import create_app
from loopprism.sessions import analysis, claude_code, codex, context
from loopprism.sessions.claude_code import message_hash
from loopprism.sessions.store import SessionStore

SID = "11111111-2222-3333-4444-555555555555"


def jl(rows):
    return "\n".join(json.dumps(r) for r in rows) + "\n"


def usage(inp=10, out=5, read=0, w5=0, w1=0):
    return {
        "input_tokens": inp,
        "output_tokens": out,
        "cache_read_input_tokens": read,
        "cache_creation": {"ephemeral_5m_input_tokens": w5, "ephemeral_1h_input_tokens": w1},
    }


def claude_session(path, with_requests=True):
    prompt = {"role": "user", "content": "fix the bug in parser.py"}
    ctx_blob = {"role": "system", "content": [{"type": "text", "text": "<system-reminder>be careful</system-reminder>"}]}
    a1 = {"role": "assistant", "content": [
        {"type": "thinking", "thinking": "", "signature": "x" * 400},
        {"type": "text", "text": "Let me look."},
        {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "parser.py"}},
    ]}
    result = {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "def parse(): pass"}]}
    shape = {"system": [{"type": "text", "text": "You are Claude Code. " * 50}],
             "tools": [{"name": "Read", "description": "Read a file", "input_schema": {"type": "object"}}]}
    h_ctx = message_hash(ctx_blob)
    h_prompt = message_hash(prompt)
    h_a1 = message_hash(a1)
    h_res = message_hash(result)
    rows = [
        {"type": "custom-title", "customTitle": "Fix parser", "sessionId": SID},
        {"type": "user", "uuid": "u1", "timestamp": "2026-10-28T10:00:00.000Z", "cwd": "/work/app", "version": "2.1.308",
         "sessionId": SID, "message": prompt},
    ]
    if with_requests:
        rows += [
            {"type": "api-request-shape", "shapeHash": "s1", "shape": shape},
            {"type": "api-request-blob", "hash": h_ctx, "message": ctx_blob},
            {"type": "api-request", "id": "r1", "timestamp": "2026-10-28T10:00:01.000Z", "shapeHash": "s1",
             "keep": 0, "tail": [h_prompt, h_ctx], "params": {"model": "claude-sonnet-5-5"}},
        ]
    rows += [
        {"type": "assistant", "uuid": "a1", "timestamp": "2026-10-28T10:00:05.000Z", "thinkingDurationMs": 1500,
         "message": {"id": "m1", "model": "claude-sonnet-5-5", "role": "assistant", "usage": usage(100, 40, 2000, 0, 500), "content": a1["content"][:1]}},
        {"type": "assistant", "uuid": "a2", "timestamp": "2026-10-28T10:00:06.000Z",
         "message": {"id": "m1", "model": "claude-sonnet-5-5", "role": "assistant", "usage": usage(100, 40, 2000, 0, 500), "content": a1["content"][1:]}},
        {"type": "user", "uuid": "u2", "timestamp": "2026-10-28T10:00:07.000Z", "message": result},
    ]
    if with_requests:
        rows.append({"type": "api-request", "id": "r2", "base": "r1", "timestamp": "2026-10-28T10:00:08.000Z",
                     "shapeHash": "s1", "keep": 2, "tail": [h_a1, h_res]})
    rows += [
        {"type": "assistant", "uuid": "a3", "timestamp": "2026-10-28T10:00:10.000Z",
         "message": {"id": "m2", "model": "claude-sonnet-5-5", "role": "assistant", "usage": usage(50, 20, 2800, 0, 0),
                     "content": [{"type": "text", "text": "Fixed it."}]}},
    ]
    with open(path, "w") as f:
        f.write(jl(rows))


class TestClaudeCode:
    def test_exact_request_reconstruction(self, tmp_path):
        p = tmp_path / f"{SID}.jsonl"
        claude_session(p)
        ps = claude_code.parse(str(p))
        assert ps.meta.title == "Fix parser" and ps.meta.project == "/work/app"
        assert ps.meta.fidelity == "exact"
        assert (ps.meta.turns, ps.meta.steps, ps.meta.tool_calls) == (1, 2, 1)
        assert ps.unresolved == 0
        s0, s1 = ps.steps
        assert len(s0.refs) == 2 and len(s1.refs) == 4  # keep 2 + 2 new
        assert s0.input_tokens == 100 and s0.cache_read_tokens == 2000 and s0.cache_write_1h_tokens == 500
        assert s0.thinking_ms == 1500 and s0.model_ms == 5000.0
        assert ps.meta.cost_usd is not None and s0.cost_usd > 0

    def test_event_kinds_and_context_classification(self, tmp_path):
        p = tmp_path / f"{SID}.jsonl"
        claude_session(p)
        ps = claude_code.parse(str(p))
        kinds = [e.kind for e in ps.events]
        assert kinds == ["user", "thinking", "assistant", "tool_call", "tool_result", "assistant"]
        tool = next(e for e in ps.events if e.kind == "tool_call")
        assert tool.tool_name == "Read" and tool.tool_input == {"file_path": "parser.py"}

    def test_step_context_sums_to_actual(self, tmp_path):
        p = tmp_path / f"{SID}.jsonl"
        claude_session(p)
        ps = claude_code.parse(str(p))
        c = context.step_context(ps, 1, detail=True)
        assert c["exact_request"] and c["actual_input"] == 2850
        assert sum(x["tokens"] for x in c["categories"]) == pytest.approx(2850, abs=len(c["categories"]))
        keys = {x["key"] for x in c["categories"]}
        assert {"system_prompt", "tool_schemas", "user", "injected", "assistant", "tool_results"} <= keys
        assert c["items"]["tool_schemas"][0]["label"] == "Read"

    def test_without_request_records_system_is_inferred(self, tmp_path):
        p = tmp_path / f"{SID}.jsonl"
        claude_session(p, with_requests=False)
        ps = claude_code.parse(str(p))
        assert ps.meta.fidelity == "estimated"
        c = context.step_context(ps, 1)
        assert not c["exact_request"]
        assert any(x["key"] == "unattributed" and x["tokens"] > 0 for x in c["categories"])

    def test_stats_and_timing(self, tmp_path):
        p = tmp_path / f"{SID}.jsonl"
        claude_session(p)
        ps = claude_code.parse(str(p))
        st = context.stats(ps)
        assert st["steps"] == 2 and st["tool_calls"] == 1 and st["human_inputs"] == 1
        assert st["window"] == 1_000_000 and st["cache_hit_pct"] > 80
        t = analysis.timing(ps)
        assert t["thinking_ms"] == 1500 and t["tokens_per_second"]


class TestFindings:
    def test_repeated_calls_and_error_streaks(self, tmp_path):
        rows = [{"type": "user", "timestamp": "2026-10-28T10:00:00.000Z", "message": {"role": "user", "content": "go"}}]
        for i in range(4):
            rows.append({"type": "assistant", "timestamp": "2026-10-28T10:00:01.000Z",
                         "message": {"id": f"m{i}", "model": "claude-sonnet-5-5", "role": "assistant", "usage": usage(),
                                     "content": [{"type": "tool_use", "id": f"t{i}", "name": "Bash", "input": {"command": "pytest"}}]}})
            rows.append({"type": "user", "timestamp": "2026-10-28T10:00:02.000Z",
                         "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"t{i}", "content": "boom", "is_error": True}]}})
        p = tmp_path / f"{SID}.jsonl"
        p.write_text(jl(rows))
        ps = claude_code.parse(str(p))
        kinds = {f["kind"] for f in analysis.findings(ps)}
        assert {"repeated_call", "error_streak"} <= kinds


class TestCodex:
    def test_parse(self, tmp_path):
        T = "turn-1"
        rows = [
            {"type": "session_meta", "timestamp": "2026-10-28T10:00:00Z", "payload": {"id": "cdx-session-1", "cwd": "/work/x", "cli_version": "0.1"}},
            {"type": "response_item", "timestamp": "2026-10-28T10:00:01Z", "payload": {"type": "additional_tools", "tools": [{"name": "exec", "description": "run"}]}},
            {"type": "response_item", "timestamp": "2026-10-28T10:00:01Z", "payload": {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "You are Codex. " * 40}]}},
            {"type": "turn_context", "timestamp": "2026-10-28T10:00:02Z", "payload": {"turn_id": T, "model": "gpt-6.1-sol"}},
            {"type": "response_item", "timestamp": "2026-10-28T10:00:02Z", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "list files"}]}},
            {"type": "response_item", "timestamp": "2026-10-28T10:00:04Z", "payload": {"type": "function_call", "name": "shell", "arguments": "{\"cmd\":\"ls\"}", "call_id": "c1"}},
            {"type": "token_usage_record", "timestamp": "2026-10-28T10:00:04Z", "ordinal": 1,
             "payload": {"turn_id": T, "root_turn_id": T, "response_id": "r1",
                         "usage": {"input_tokens": 1000, "cached_input_tokens": 600, "output_tokens": 30}}},
            {"type": "event_msg", "timestamp": "2026-10-28T10:00:04Z", "payload": {"type": "token_count", "info": {"model_context_window": 258400}}},
            {"type": "response_item", "timestamp": "2026-10-28T10:00:05Z", "payload": {"type": "function_call_output", "call_id": "c1", "output": "a.py"}},
            {"type": "response_item", "timestamp": "2026-10-28T10:00:06Z", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Done."}]}},
            {"type": "token_usage_record", "timestamp": "2026-10-28T10:00:06Z", "ordinal": 2,
             "payload": {"turn_id": T, "root_turn_id": T, "response_id": "r2",
                         "usage": {"input_tokens": 1100, "cached_input_tokens": 1000, "output_tokens": 10}}},
        ]
        p = tmp_path / "rollout-2026-10-28T10-00-00-cdx-session-1.jsonl"
        p.write_text(jl(rows))
        ps = codex.parse(str(p))
        assert ps.meta.id == "cdx-session-1" and ps.meta.project == "/work/x"
        assert (ps.meta.turns, ps.meta.steps, ps.meta.tool_calls) == (1, 2, 1)
        s0 = ps.steps[0]
        assert (s0.input_tokens, s0.cache_read_tokens, s0.output_tokens) == (400, 600, 30)  # cached split out of input
        assert s0.context_window is None and ps.steps[1].context_window == 258400
        assert ps.events[-1].kind == "assistant" and ps.events[-1].step == 1
        c = context.step_context(ps, 1)
        assert c["actual_input"] == 1100 and not c["exact_request"]
        assert {"system_prompt", "tool_schemas"} <= {x["key"] for x in c["categories"]}


@pytest.fixture
def home(tmp_path, monkeypatch):
    claude = tmp_path / ".claude" / "projects" / "-work-app"
    claude.mkdir(parents=True)
    claude_session(claude / f"{SID}.jsonl")
    codex_dir = tmp_path / ".codex" / "sessions" / "2026" / "10" / "28"
    codex_dir.mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / ".claude"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


class TestStore:
    def test_index_search_and_incremental(self, home):
        store = SessionStore(None)
        assert store.refresh(5)["indexed"] == 1
        (row,) = store.list()
        assert row["title"] == "Fix parser" and row["agent"] == "claude-code" and row["steps"] == 2
        assert store.list(q="parser")[0]["id"] == SID
        assert store.list(q="nonexistentterm") == []
        assert store.refresh(5)["indexed"] == 0  # unchanged files are not re-parsed
        assert store.load(SID).meta.title == "Fix parser"

    def test_removed_files_disappear(self, home):
        store = SessionStore(None)
        store.refresh(5)
        os.remove(store.find(SID)["path"])
        store.refresh(5)
        assert store.list() == []


@pytest.fixture
async def api(collector, home):
    app = create_app(collector=collector, dashboard_enabled=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1") as c:
        yield c


class TestApi:
    @pytest.mark.asyncio
    async def test_list_get_context(self, api):
        r = await api.get("/api/sessions")
        assert r.status_code == 200 and r.json()["total"] == 1
        sid = r.json()["sessions"][0]["id"]
        d = (await api.get(f"/api/sessions/{sid}")).json()
        assert d["session"]["resume_command"] == f"claude --resume {SID}"  # /work/app does not exist here
        ev = (await api.get(f"/api/sessions/{sid}/events", params={"kinds": "user,assistant"})).json()
        assert [e["kind"] for e in ev["events"]] == ["user", "assistant", "assistant"]
        ctx = (await api.get(f"/api/sessions/{sid}/context")).json()
        assert len(ctx["trend"]) == 2 and ctx["stats"]["fidelity"] == "exact"
        step = (await api.get(f"/api/sessions/{sid}/context/1")).json()
        assert step["items"]["tool_results"]
        traj = (await api.get(f"/api/sessions/{sid}/trajectory")).json()
        assert len(traj["steps"]) == 2 and traj["turns"][0]["turn"] == 1
        assert (await api.get(f"/api/sessions/{sid}/timing")).json()["thinking_ms"] == 1500
        md = (await api.get(f"/api/sessions/{sid}/export.md")).text
        assert md.startswith("# Fix parser") and "fix the bug" in md

    @pytest.mark.asyncio
    async def test_delete_moves_to_trash(self, api, home):
        sid = (await api.get("/api/sessions")).json()["sessions"][0]["id"]
        r = await api.post(f"/api/sessions/{sid}/delete")
        assert r.status_code == 200
        assert not os.path.exists(home / ".claude" / "projects" / "-work-app" / f"{SID}.jsonl")
        assert os.path.exists(r.json()["trashed"])
        assert (await api.get("/api/sessions")).json()["total"] == 0

    @pytest.mark.asyncio
    async def test_foreign_pages_and_hosts_are_refused(self, api):
        r = await api.get("/api/sessions", headers={"Origin": "https://evil.example"})
        assert r.status_code == 403
        r = await api.post("/api/sessions/x/delete", headers={"Origin": "https://evil.example"})
        assert r.status_code == 403
        r = await api.get("/api/sessions", headers={"Host": "evil.example"})
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_unknown_session(self, api):
        assert (await api.get("/api/sessions/nope")).status_code == 404
