"""Cursor adapter: the key-value database in both layouts, tools, discovery and the store."""

import json
import sqlite3

import pytest
from httpx import ASGITransport, AsyncClient

from loopprism.api.app import create_app
from loopprism.sessions import cursor
from loopprism.sessions.store import SessionStore

CID = "c0ffee00-0000-4000-8000-000000000001"


def make_db(user_dir, *, new_layout=True, extra_bubbles=()):
    (user_dir / "globalStorage").mkdir(parents=True)
    ws = user_dir / "workspaceStorage" / "ws1"
    ws.mkdir(parents=True)
    (ws / "workspace.json").write_text(json.dumps({"folder": "file:///work/my%20app"}))
    db = user_dir / "globalStorage" / "state.vscdb"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE cursorDiskKV (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)")
    c.execute("CREATE TABLE composerHeaders (composerId TEXT PRIMARY KEY, isSubagent INTEGER)")
    user = {"type": 1, "bubbleId": "u1", "text": "list the files", "createdAt": "2026-10-29T14:00:00.000Z",
            "modelInfo": {"modelName": "grok-4.6"}}
    step0 = {"type": 2, "bubbleId": "u1/s:0", "createdAt": "2026-10-29T14:00:02.000Z", "thinking": {"text": "use ls"}}
    step1 = {"type": 2, "bubbleId": "u1/s:1", "createdAt": "2026-10-29T14:00:03.000Z",
             "toolFormerData": {"name": "run_terminal_cmd", "toolCallId": "t1", "status": "completed",
                                "rawArgs": json.dumps({"command": "ls"}), "result": json.dumps({"output": "a.py"})}}
    step2 = {"type": 2, "bubbleId": "u1/s:2", "createdAt": "2026-10-29T14:00:04.000Z", "text": "One file: a.py",
             "toolFormerData": None}
    step3 = {"type": 2, "bubbleId": "u1/s:3", "createdAt": "2026-10-29T14:00:05.000Z",
             "toolFormerData": {"name": "read_file", "toolCallId": "t2", "status": "error", "rawArgs": "{}", "result": ""}}
    bubbles = [user, step0, step1, step3, step2, *extra_bubbles]
    heads = [{"bubbleId": b["bubbleId"], "type": b["type"]} for b in bubbles]
    composer = {"composerId": CID, "name": "General chat", "createdAt": 1793284504405, "lastUpdatedAt": 1793284510000,
                "workspaceIdentifier": {"id": "ws1"}, "modelConfig": {"modelName": "default"}}
    if new_layout:
        c.execute("INSERT INTO cursorDiskKV VALUES (?, ?)", (f"composerConvHeaders:{CID}:000000", json.dumps(heads)))
    else:
        composer["fullConversationHeadersOnly"] = heads
    c.execute("INSERT INTO cursorDiskKV VALUES (?, ?)", (f"composerData:{CID}", json.dumps(composer)))
    c.execute("INSERT INTO cursorDiskKV VALUES (?, ?)", ("composerData:draft", json.dumps({"composerId": "draft"})))
    for b in bubbles:
        c.execute("INSERT INTO cursorDiskKV VALUES (?, ?)", (f"bubbleId:{CID}:{b['bubbleId']}", json.dumps(b)))
    c.commit()
    c.close()
    return str(db)


@pytest.fixture
def user_dir(tmp_path, monkeypatch):
    d = tmp_path / "User"
    monkeypatch.setenv("CURSOR_USER_DIR", str(d))
    return d


@pytest.mark.parametrize("new_layout", [True, False])
def test_conversation_is_parsed_in_both_layouts(user_dir, new_layout):
    db = make_db(user_dir, new_layout=new_layout)
    found = cursor.discover(db)
    assert list(found) == [f"{db}#{CID}"]  # the empty draft is not a session
    ps = cursor.parse(f"{db}#{CID}")
    m = ps.meta
    assert (m.agent, m.title, m.project, m.turns, m.tool_calls) == ("cursor", "list the files", "/work/my app", 1, 2)
    assert m.models == ["grok-4.6"] and m.cost_usd is None
    assert [e.kind for e in ps.events] == ["user", "thinking", "tool_call", "tool_result", "tool_call", "tool_result", "assistant"]
    calls = [e for e in ps.events if e.kind == "tool_call"]
    assert calls[0].tool_name == "run_terminal_cmd" and calls[0].tool_input == {"command": "ls"}
    results = [e for e in ps.events if e.kind == "tool_result"]
    assert (results[0].is_error, results[1].is_error) == (False, True)
    assert '"output": "a.py"' in results[0].text


def test_subagent_conversations_are_left_out_and_the_header_name_wins(user_dir):
    db = make_db(user_dir)
    c = sqlite3.connect(db)
    c.execute("INSERT INTO composerHeaders VALUES (?, 1)", (CID,))
    c.commit()
    c.close()
    assert cursor.discover(db) == {}
    c = sqlite3.connect(db)
    c.execute("DELETE FROM composerHeaders")
    value = json.loads(c.execute("SELECT value FROM cursorDiskKV WHERE key = ?", (f"composerData:{CID}",)).fetchone()[0])
    value["name"] = "Fix the build"
    c.execute("INSERT INTO cursorDiskKV VALUES (?, ?)", (f"composerData:{CID}", json.dumps(value)))
    c.commit()
    c.close()
    assert cursor.parse(f"{db}#{CID}").meta.title == "Fix the build"


@pytest.mark.asyncio
async def test_store_and_api_list_cursor_sessions_read_only(user_dir, tmp_path, collector):
    db = make_db(user_dir)
    store = SessionStore(index_path=str(tmp_path / "idx.db"))
    store.refresh(5)
    (row,) = [r for r in store.list() if r["agent"] == "cursor"]
    assert row["title"] == "list the files"
    app = create_app(collector=collector, dashboard_enabled=False)
    app.state.sessions = store
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1") as api:
        body = (await api.get(f"/api/sessions/{row['id']}")).json()
        assert body["session"]["read_only"] is True
        r = await api.get(f"/api/sessions/{row['id']}/trajectory")
        assert r.status_code == 200
