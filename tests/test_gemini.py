"""Gemini CLI adapter: both file formats, patches and rewinds, token mapping, the store and the API."""

import json
import os

import pytest
from httpx import ASGITransport, AsyncClient

from loopprism.api.app import create_app
from loopprism.sessions import gemini
from loopprism.sessions.store import SessionStore

HEADER = {"sessionId": "sess-1", "projectHash": "abc", "startTime": "2026-10-01T10:00:00.000Z", "kind": "main"}


def messages():
    return [
        {"id": "m1", "timestamp": "2026-10-01T10:00:01.000Z", "type": "user", "content": [{"text": "fix the failing test"}]},
        {"id": "m2", "timestamp": "2026-10-01T10:00:05.000Z", "type": "gemini", "content": "Looking at it.",
         "model": "gemini-2.5-pro",
         "thoughts": [{"subject": "Plan", "description": "read the test first", "timestamp": "2026-10-01T10:00:03.000Z"}],
         "tokens": {"input": 10000, "output": 200, "cached": 6000, "thoughts": 100, "tool": 0, "total": 10300},
         "toolCalls": [{"id": "c1", "name": "run_shell_command", "args": {"command": "pytest"}, "status": "success",
                        "timestamp": "2026-10-01T10:00:06.000Z",
                        "result": [{"functionResponse": {"id": "c1", "name": "run_shell_command", "response": {"output": "1 failed"}}}]},
                       {"id": "c2", "name": "read_file", "args": {"path": "a.py"}, "status": "error",
                        "timestamp": "2026-10-01T10:00:07.000Z",
                        "result": [{"functionResponse": {"id": "c2", "name": "read_file", "response": {"error": "no such file"}}}]}]},
        {"id": "m3", "timestamp": "2026-10-01T10:00:09.000Z", "type": "info", "content": "ignored"},
        {"id": "m4", "timestamp": "2026-10-01T10:00:10.000Z", "type": "gemini", "content": "Fixed.", "model": "gemini-2.5-pro",
         "tokens": {"input": 12000, "output": 50, "cached": 10000, "total": 12050}},
    ]


def write_jsonl(path, extra=()):
    rows = [HEADER, *messages(), *extra]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_CLI_HOME", str(tmp_path))
    chats = tmp_path / ".gemini" / "tmp" / "myproj" / "chats"
    chats.mkdir(parents=True)
    (tmp_path / ".gemini" / "tmp" / "myproj" / ".project_root").write_text("/work/myproj\n")
    return chats


def test_jsonl_session_is_parsed_with_tools_thinking_and_usage(home):
    f = home / "session-2026-10-01T10-00-abcd1234.jsonl"
    write_jsonl(f)
    ps = gemini.parse(str(f))
    m = ps.meta
    assert (m.id, m.agent, m.project, m.title) == ("sess-1", "gemini", "/work/myproj", "fix the failing test")
    assert (m.turns, m.steps, m.tool_calls) == (1, 2, 2)
    kinds = [e.kind for e in ps.events]
    assert kinds == ["user", "thinking", "assistant", "tool_call", "tool_result", "tool_call", "tool_result", "assistant"]
    results = [e for e in ps.events if e.kind == "tool_result"]
    assert [(r.text, r.is_error) for r in results] == [("1 failed", False), ("no such file", True)]
    s0, s1 = ps.steps
    # the prompt count includes the cached part; thinking tokens are billed as output
    assert (s0.input_tokens, s0.cache_read_tokens, s0.output_tokens) == (4000, 6000, 300)
    assert (s1.input_tokens, s1.cache_read_tokens, s1.output_tokens) == (2000, 10000, 50)
    assert m.models == ["gemini-2.5-pro"] and m.cost_usd and m.cost_usd > 0


def test_legacy_json_document_is_parsed_the_same(home):
    f = home / "session-2026-10-01T10-00-abcd1234.json"
    f.write_text(json.dumps({**HEADER, "lastUpdated": "2026-10-01T10:00:10.000Z", "messages": messages()}))
    ps = gemini.parse(str(f))
    assert (ps.meta.turns, ps.meta.steps, ps.meta.tool_calls) == (1, 2, 2)
    assert ps.meta.ended_at == "2026-10-01T10:00:10.000Z"


def test_patches_rewinds_and_metadata_updates_are_applied(home):
    f = home / "session-x.jsonl"
    write_jsonl(f, extra=[
        {"$patch": {"id": "m4", "content": "Fixed, and tested."}},
        {"$patch": {"updates": [{"id": "m2", "toolCalls": [{"id": "c1", "result": [{"functionResponse": {"response": {"output": "all passed"}}}]}]}]}},
        {"$set": {"summary": "Fixing the test"}},
    ])
    ps = gemini.parse(str(f))
    assert ps.meta.title == "Fixing the test"
    assert [e.text for e in ps.events if e.kind == "assistant"][-1] == "Fixed, and tested."
    assert "all passed" in [e.text for e in ps.events if e.kind == "tool_result"]

    write_jsonl(f, extra=[{"$rewindTo": "m2"}])
    ps = gemini.parse(str(f))
    assert (ps.meta.turns, ps.meta.steps) == (1, 0)  # the answer and everything after it are gone


def test_discover_prefers_the_jsonl_of_a_session_written_twice(home):
    (home / "session-a.json").write_text("{}")
    (home / "session-a.jsonl").write_text("{}\n")
    (home / "session-b.json").write_text("{}")
    (home / "notes.txt").write_text("x")
    found = sorted(os.path.basename(p) for p in gemini.discover(gemini.gemini_root()))
    assert found == ["session-a.jsonl", "session-b.json"]


@pytest.mark.asyncio
async def test_store_and_api_list_gemini_sessions_read_only(home, tmp_path, collector):
    write_jsonl(home / "session-2026-10-01T10-00-abcd1234.jsonl")
    store = SessionStore(index_path=str(tmp_path / "idx.db"))
    store.refresh(5)
    (row,) = [r for r in store.list() if r["agent"] == "gemini"]
    assert row["title"] == "fix the failing test" and row["cost_usd"]
    app = create_app(collector=collector, dashboard_enabled=False)
    app.state.sessions = store
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1") as api:
        body = (await api.get(f"/api/sessions/{row['id']}")).json()
        assert body["session"]["read_only"] is True
        for view in ("context", "trajectory", "cost"):
            r = await api.get(f"/api/sessions/{row['id']}/{view}")
            assert r.status_code == 200, view
