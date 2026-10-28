"""Tests for agent hook event ingest (Claude Code / Codex)."""

import pytest
from httpx import ASGITransport, AsyncClient

from loopprism.api.app import create_app
from loopprism.trace.ingest import split_mcp_tool, truncate


@pytest.fixture
async def api(collector):
    app = create_app(collector=collector, dashboard_enabled=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def ev(event, session="s1", **kw):
    return {"agent": "claude-code", "event": event, "session_id": session, **kw}


async def send(api, *events, headers=None):
    r = await api.post("/api/ingest/events", json={"events": list(events)}, headers=headers)
    return r


async def runs(collector):
    return await collector.list_traces(limit=50)


class TestHelpers:
    def test_split_mcp_tool(self):
        assert split_mcp_tool("mcp__github__search_repos") == ("github", "search_repos")
        assert split_mcp_tool("mcp__a__b__c") == ("a", "b__c")
        assert split_mcp_tool("Bash") == (None, "Bash")
        assert split_mcp_tool("mcp__broken") == (None, "mcp__broken")

    def test_truncate(self):
        big = {"a": "x" * 5000, "b": [1, 2], "c": {"d": {"e": {"f": {"g": {"h": {"i": "deep"}}}}}}}
        out = truncate(big)
        assert len(out["a"]) < 2100 and "more chars" in out["a"]
        assert out["b"] == [1, 2]
        assert out["c"]["d"]["e"]["f"]["g"]["h"] == "..."


class TestRunLifecycle:
    @pytest.mark.asyncio
    async def test_prompt_tools_stop_make_one_run(self, api, collector):
        r = await send(
            api,
            ev("prompt", prompt="Fix the failing test\nplease"),
            ev("tool", tool_name="Bash", tool_input={"command": "pytest"},
               tool_response={"stdout": "1 failed"}, tool_use_id="t1", duration_ms=1500),
            ev("tool", tool_name="mcp__github__search", tool_input={"q": "x"},
               tool_response="ok", tool_use_id="t2", duration_ms=300),
            ev("tool_failure", tool_name="Edit", error="no match", tool_use_id="t3", duration_ms=5),
            ev("stop"),
        )
        assert r.status_code == 200 and r.json()["accepted"] == 5

        (run,) = await runs(collector)
        trace, spans = await collector.get_trace(run["id"])
        assert trace["status"] == "succeeded" and trace["ended_at"]
        assert trace["session_id"] == "s1" and trace["correlation_source"] == "explicit"
        assert trace["root_span_type"] == "agent.run"
        assert trace["root_span_name"] == "Fix the failing test please"
        assert trace["span_count"] == 3 and trace["error_count"] == 1

        assert [s["seq"] for s in spans] == [1, 2, 3]
        bash, gh, edit = spans
        assert (bash["tool_name"], bash["mcp_server_name"]) == ("Bash", None)
        assert (gh["tool_name"], gh["mcp_server_name"]) == ("search", "github")
        assert bash["tool_call_id"] == "t1" and bash["latency_ms"] == 1500
        assert bash["span_type"] == "agent.tool.call"
        assert edit["status"] == "error" and edit["result_is_error"] == 1

    @pytest.mark.asyncio
    async def test_spans_are_backdated_by_duration(self, api, collector):
        await send(api, ev("prompt", prompt="p"),
                   ev("tool", tool_name="Bash", duration_ms=4000, tool_use_id="t"))
        (run,) = await runs(collector)
        _, (span,) = await collector.get_trace(run["id"])
        cursor = await collector._conn.execute(
            "SELECT (julianday(end_time) - julianday(start_time)) * 86400 AS secs FROM spans"
        )
        assert 3 <= (await cursor.fetchone())["secs"] <= 6

    @pytest.mark.asyncio
    async def test_new_prompt_abandons_unfinished_run(self, api, collector):
        await send(api, ev("prompt", prompt="first"), ev("tool", tool_name="Bash"))
        await send(api, ev("prompt", prompt="second"), ev("stop"))
        by_name = {t["root_span_name"]: t for t in await runs(collector)}
        assert by_name["first"]["status"] == "abandoned"
        assert by_name["second"]["status"] == "succeeded"

    @pytest.mark.asyncio
    async def test_session_end_abandons_open_run_and_stop_is_final(self, api, collector):
        await send(api, ev("prompt", prompt="a"), ev("session_end"))
        await send(api, ev("prompt", prompt="b"), ev("stop"), ev("session_end"))
        by_name = {t["root_span_name"]: t for t in await runs(collector)}
        assert by_name["a"]["status"] == "abandoned"
        assert by_name["b"]["status"] == "succeeded"

    @pytest.mark.asyncio
    async def test_tool_without_prompt_still_recorded(self, api, collector):
        await send(api, ev("tool", tool_name="Read", tool_use_id="t"))
        (run,) = await runs(collector)
        assert run["root_span_name"] == "(no prompt captured)" and run["span_count"] == 1

    @pytest.mark.asyncio
    async def test_sessions_and_agents_are_separate_runs(self, api, collector):
        await send(api, ev("prompt", session="a", prompt="x"), ev("prompt", session="b", prompt="y"))
        await send(api, ev("tool", session="a", tool_name="Bash"))
        counts = {t["session_id"]: t["span_count"] for t in await runs(collector)}
        assert counts == {"a": 1, "b": 0}

    @pytest.mark.asyncio
    async def test_huge_payloads_are_capped(self, api, collector):
        await send(api, ev("prompt", prompt="p"),
                   ev("tool", tool_name="Read", tool_input={"p": "x" * 50_000},
                      tool_response={"content": "y" * 50_000}))
        (run,) = await runs(collector)
        _, (span,) = await collector.get_trace(run["id"])
        assert len(span["tool_arguments"]) < 3000
        assert len(span["result_content_preview"]) <= 500

    @pytest.mark.asyncio
    async def test_concurrent_first_tools_share_one_run(self, api, collector):
        import asyncio

        await asyncio.gather(*[
            send(api, ev("tool", tool_name="Bash", tool_use_id=f"t{i}")) for i in range(8)
        ])
        (run,) = await runs(collector)
        assert run["span_count"] == 8


class TestValidationAndSafety:
    @pytest.mark.asyncio
    async def test_rejects_browser_origin(self, api, collector):
        r = await send(api, ev("prompt", prompt="x"), headers={"Origin": "https://evil.example"})
        assert r.status_code == 403
        assert await runs(collector) == []

    @pytest.mark.asyncio
    async def test_rejects_bad_events(self, api):
        assert (await send(api, {"agent": "a", "event": "nope", "session_id": "s"})).status_code == 422
        assert (await api.post("/api/ingest/events", json={"events": []})).status_code == 422
        assert (await api.post("/api/ingest/events", json={"events": [{"agent": "a"}]})).status_code == 422

    @pytest.mark.asyncio
    async def test_unknown_extra_fields_are_ignored(self, api):
        r = await send(api, ev("session_start", brand_new_field=1))
        assert r.status_code == 200
