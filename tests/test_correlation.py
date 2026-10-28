"""Tests for run correlation: traceparent, Mcp-Session-Id, idle-gap heuristic."""

import json

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route
from starlette.testclient import TestClient

from loopprism.proxy.http_handler import MCPHttpHandler
from loopprism.trace.collector import TraceCollector
from loopprism.trace.correlation import (
    EXPLICIT,
    HEURISTIC,
    SESSION,
    RunCorrelator,
    parse_traceparent,
)

TRACE = "0af7651916cd43dd8448eb211c80319c"
SPAN = "b7ad6b7169203331"
TRACEPARENT = f"00-{TRACE}-{SPAN}-01"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class TestParseTraceparent:
    def test_valid(self):
        parsed = parse_traceparent(TRACEPARENT)
        assert parsed.trace_id == TRACE
        assert parsed.parent_span_id == SPAN

    def test_uppercase_is_normalised(self):
        assert parse_traceparent(TRACEPARENT.upper()).trace_id == TRACE

    @pytest.mark.parametrize(
        "value",
        [
            None,
            42,
            "",
            "garbage",
            f"00-{'0' * 32}-{SPAN}-01",  # all-zero trace id
            f"00-{TRACE}-{'0' * 16}-01",  # all-zero span id
            f"ff-{TRACE}-{SPAN}-01",  # forbidden version
            f"00-{TRACE[:-1]}-{SPAN}-01",  # short trace id
        ],
    )
    def test_invalid(self, value):
        assert parse_traceparent(value) is None


class TestRunCorrelator:
    def make(self, idle=30.0):
        clock = FakeClock()
        return RunCorrelator(idle_seconds=idle, clock=clock), clock

    def test_header_traceparent_is_explicit(self):
        c, _ = self.make()
        r = c.resolve({"traceparent": TRACEPARENT}, {}, "srv")
        assert (r.trace_id, r.source) == (TRACE, EXPLICIT)
        assert r.remote_parent_span_id == SPAN

    def test_meta_traceparent_is_explicit(self):
        c, _ = self.make()
        body = {"params": {"_meta": {"traceparent": TRACEPARENT}}}
        r = c.resolve({}, body, "srv")
        assert (r.trace_id, r.source) == (TRACE, EXPLICIT)

    def test_header_beats_meta(self):
        c, _ = self.make()
        other = f"00-{'a' * 32}-{SPAN}-01"
        body = {"params": {"_meta": {"traceparent": other}}}
        assert c.resolve({"traceparent": TRACEPARENT}, body, "srv").trace_id == TRACE

    def test_invalid_traceparent_falls_through(self):
        c, _ = self.make()
        r = c.resolve({"traceparent": "nope"}, {}, "srv", client="1.1.1.1")
        assert r.source == HEURISTIC

    def test_legacy_trace_id_header(self):
        c, _ = self.make()
        assert c.resolve({"x-loopprism-trace-id": "abc"}, {}, "srv").trace_id == "abc"
        assert c.resolve({"x-toolglass-trace-id": "def"}, {}, "srv").source == EXPLICIT

    def test_explicit_keeps_session_id(self):
        c, _ = self.make()
        r = c.resolve(
            {"traceparent": TRACEPARENT, "mcp-session-id": "s1"}, {}, "srv"
        )
        assert r.source == EXPLICIT and r.session_id == "s1"

    def test_session_groups_requests(self):
        c, clock = self.make()
        h = {"mcp-session-id": "s1"}
        a = c.resolve(h, {}, "srv")
        clock.now += 10
        b = c.resolve(h, {}, "srv")
        assert a.source == SESSION and a.trace_id == b.trace_id

    def test_sessions_are_separate_runs(self):
        c, _ = self.make()
        a = c.resolve({"mcp-session-id": "s1"}, {}, "srv")
        b = c.resolve({"mcp-session-id": "s2"}, {}, "srv")
        assert a.trace_id != b.trace_id

    def test_same_session_id_on_different_servers_is_separate(self):
        c, _ = self.make()
        a = c.resolve({"mcp-session-id": "s1"}, {}, "github")
        b = c.resolve({"mcp-session-id": "s1"}, {}, "slack")
        assert a.trace_id != b.trace_id

    def test_idle_gap_starts_new_run(self):
        c, clock = self.make(idle=30)
        h = {"mcp-session-id": "s1"}
        a = c.resolve(h, {}, "srv")
        clock.now += 30  # exactly the gap: still the same run
        assert c.resolve(h, {}, "srv").trace_id == a.trace_id
        clock.now += 31
        assert c.resolve(h, {}, "srv").trace_id != a.trace_id

    def test_activity_extends_the_run(self):
        c, clock = self.make(idle=30)
        h = {"mcp-session-id": "s1"}
        first = c.resolve(h, {}, "srv")
        for _ in range(5):
            clock.now += 20  # always inside the gap, total far beyond it
            assert c.resolve(h, {}, "srv").trace_id == first.trace_id

    def test_initialize_starts_new_run(self):
        c, _ = self.make()
        h = {"mcp-session-id": "s1"}
        a = c.resolve(h, {}, "srv", method="tools/call")
        b = c.resolve(h, {}, "srv", method="initialize")
        c2 = c.resolve(h, {}, "srv", method="tools/call")
        assert a.trace_id != b.trace_id and b.trace_id == c2.trace_id

    def test_heuristic_groups_by_client_and_user_agent(self):
        c, _ = self.make()
        h = {"user-agent": "agent/1"}
        a = c.resolve(h, {}, "github", client="10.0.0.1")
        b = c.resolve(h, {}, "slack", client="10.0.0.1")  # same client, other server
        other_ua = c.resolve({"user-agent": "agent/2"}, {}, "github", client="10.0.0.1")
        other_ip = c.resolve(h, {}, "github", client="10.0.0.2")
        assert a.source == HEURISTIC
        assert a.trace_id == b.trace_id
        assert len({a.trace_id, other_ua.trace_id, other_ip.trace_id}) == 3

    def test_bind_session_joins_initialize_run(self):
        c, _ = self.make()
        init = c.resolve({"user-agent": "a"}, {}, "srv", client="x", method="initialize")
        c.bind_session("srv", "issued", init)
        follow = c.resolve({"mcp-session-id": "issued"}, {}, "srv", client="x")
        assert follow.trace_id == init.trace_id and follow.source == SESSION

    def test_old_entries_are_pruned(self):
        c, clock = self.make(idle=1)
        for i in range(300):
            c.resolve({"mcp-session-id": f"s{i}"}, {}, "srv")
        clock.now += 10
        c.resolve({"mcp-session-id": "late"}, {}, "srv")
        assert len(c._runs) < 300


def tools_call(name="echo", id_="1", meta=None):
    params = {"name": name, "arguments": {}}
    if meta:
        params["_meta"] = meta
    return {"jsonrpc": "2.0", "id": id_, "method": "tools/call", "params": params}


@pytest.fixture
async def proxy(db_path):
    """A handler wired to an in-process backend; yields (client, collector, clock)."""
    collector = TraceCollector(db_path)
    await collector.initialize()
    clock = FakeClock()

    def backend(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        headers = {}
        if body.get("method") == "initialize":
            headers["Mcp-Session-Id"] = "srv-session-1"
        return httpx.Response(
            200,
            headers=headers,
            json={"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": []}},
        )

    handler = MCPHttpHandler(
        collector,
        client=httpx.AsyncClient(transport=httpx.MockTransport(backend)),
        correlator=RunCorrelator(idle_seconds=30, clock=clock),
    )

    async def endpoint(request: Request):
        return await handler.handle(request, "mock", "http://backend")

    app = Starlette(routes=[Route("/{path:path}", endpoint, methods=["POST"])])
    yield TestClient(app), collector, clock
    await collector.close()


async def runs(collector):
    return await collector.list_traces(limit=50)


class TestProxyCorrelation:
    @pytest.mark.asyncio
    async def test_traceparent_header_sets_run_and_remote_parent(self, proxy):
        client, collector, _ = proxy
        r = client.post("/mock", json=tools_call(), headers={"traceparent": TRACEPARENT})
        assert r.headers["X-LoopPrism-Trace-Id"] == TRACE

        trace, spans = await collector.get_trace(TRACE)
        assert trace["correlation_source"] == EXPLICIT
        # The caller's span is not part of this run, so it must not become
        # parent_span_id (the dashboard would drop the span as an orphan).
        assert spans[0]["parent_span_id"] is None
        assert json.loads(spans[0]["attributes_json"])["remote_parent_span_id"] == SPAN

    @pytest.mark.asyncio
    async def test_meta_traceparent(self, proxy):
        client, collector, _ = proxy
        client.post("/mock", json=tools_call(meta={"traceparent": TRACEPARENT}))
        trace, _ = await collector.get_trace(TRACE)
        assert trace["correlation_source"] == EXPLICIT

    @pytest.mark.asyncio
    async def test_session_header_groups_calls_into_one_run(self, proxy):
        client, collector, _ = proxy
        h = {"Mcp-Session-Id": "s1"}
        for i in range(3):
            client.post("/mock", json=tools_call(id_=str(i)), headers=h)
        client.post("/mock", json=tools_call(), headers={"Mcp-Session-Id": "s2"})
        for t in await runs(collector):
            await collector.finalize_trace(t["id"])

        traces = await runs(collector)
        assert len(traces) == 2
        by_session = {t["session_id"]: t for t in traces}
        assert by_session["s1"]["correlation_source"] == SESSION
        assert by_session["s1"]["span_count"] == 3
        assert by_session["s2"]["span_count"] == 1

    @pytest.mark.asyncio
    async def test_idle_gap_splits_sessionless_traffic(self, proxy):
        client, collector, clock = proxy
        client.post("/mock", json=tools_call(id_="1"))
        clock.now += 5
        client.post("/mock", json=tools_call(id_="2"))
        clock.now += 60
        client.post("/mock", json=tools_call(id_="3"))

        traces = await runs(collector)
        assert sorted(t["span_count"] for t in traces) == [1, 2]
        assert {t["correlation_source"] for t in traces} == {HEURISTIC}

    @pytest.mark.asyncio
    async def test_initialize_session_is_bound_to_its_run(self, proxy):
        client, collector, _ = proxy
        init = {"jsonrpc": "2.0", "id": "i", "method": "initialize", "params": {}}
        client.post("/mock", json=init)
        client.post(
            "/mock", json=tools_call(), headers={"Mcp-Session-Id": "srv-session-1"}
        )

        traces = await runs(collector)
        assert len(traces) == 1
        assert traces[0]["span_count"] == 2


class TestSessionLabelling:
    """A run opened at initialize learns its session id from the response."""

    @pytest.mark.asyncio
    async def test_initialize_run_is_labelled_with_issued_session(self, proxy):
        client, collector, _ = proxy
        init = {"jsonrpc": "2.0", "id": "i", "method": "initialize", "params": {}}
        client.post("/mock", json=init)
        client.post(
            "/mock", json=tools_call(), headers={"Mcp-Session-Id": "srv-session-1"}
        )
        (trace,) = await runs(collector)
        assert trace["session_id"] == "srv-session-1"
        assert trace["conversation_id"] == "srv-session-1"
        assert trace["correlation_source"] == SESSION

    @pytest.mark.asyncio
    async def test_tag_run_never_downgrades_or_overwrites(self, collector):
        tid = await collector.create_trace(
            session_id="first", correlation_source="explicit"
        )
        await collector.tag_run(tid, session_id="second", correlation_source="heuristic")
        trace, _ = await collector.get_trace(tid)
        assert trace["session_id"] == "first"
        assert trace["correlation_source"] == "explicit"

        t2 = await collector.create_trace(correlation_source="heuristic")
        await collector.tag_run(t2, session_id="s", correlation_source="session")
        await collector.tag_run(t2, correlation_source="heuristic")
        trace2, _ = await collector.get_trace(t2)
        assert trace2["correlation_source"] == "session"
        assert trace2["session_id"] == "s"
