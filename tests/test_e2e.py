"""End-to-end smoke test: mock MCP server -> real `lprism proxy` -> HTTP API.

Starts the actual CLI in a subprocess on free ports with a temporary database,
sends MCP traffic through it over real sockets, then checks what the API and
dashboard report. Nothing in the proxy or API is mocked.
"""

import itertools
import json
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest

TRACEPARENT_TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
TRACEPARENT = f"00-{TRACEPARENT_TRACE}-00f067aa0ba902b7-01"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def mock_backend():
    sessions = itertools.count(1)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            method = body.get("method")
            headers = {}
            if method == "tools/call":
                name = body["params"]["name"]
                result = {
                    "content": [{"type": "text", "text": "x" * (2000 if name == "big" else 20)}],
                    "isError": name == "fail",
                }
            elif method == "initialize":
                result = {"protocolVersion": "2024-11-05", "serverInfo": {"name": "mock"}}
                headers["Mcp-Session-Id"] = f"sess-{next(sessions)}"
            else:
                result = {"tools": [{"name": "echo"}]}
            out = json.dumps({"jsonrpc": "2.0", "id": body.get("id"), "result": result}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            for k, v in headers.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture(scope="module")
def stack(mock_backend, tmp_path_factory):
    """Run `lprism proxy` for real; yield (proxy_url, api_url)."""
    db = tmp_path_factory.mktemp("e2e") / "traces.db"
    proxy_port, api_port = free_port(), free_port()
    # To a file, not a pipe nobody reads: a full pipe blocks the server (Windows pipes are tiny).
    log_path = db.parent / "proxy.log"
    log = open(log_path, "wb")
    proc = subprocess.Popen(
        [
            sys.executable, "-c", "from loopprism.cli.main import app; app()",
            "proxy", "--port", str(proxy_port), "--dashboard-port", str(api_port),
            "--db", str(db),
        ],
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    proxy_url = f"http://127.0.0.1:{proxy_port}"
    api_url = f"http://127.0.0.1:{api_port}"
    try:
        deadline = time.monotonic() + 20
        while True:
            if proc.poll() is not None:
                pytest.fail(f"proxy exited early:\n{log_path.read_text(errors='replace')}")
            try:
                if (
                    httpx.get(f"{proxy_url}/health", timeout=1).status_code == 200
                    and httpx.get(f"{api_url}/api/health", timeout=1).status_code == 200
                ):
                    break
            except httpx.TransportError:
                pass
            if time.monotonic() > deadline:
                pytest.fail("proxy did not become healthy in 20s")
            time.sleep(0.2)
        yield proxy_url, api_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()


class Client:
    """Talks to the mock MCP server through the proxy, reads results via the API."""

    def __init__(self, proxy_url, api_url, backend):
        self.proxy_url, self.api_url, self.backend = proxy_url, api_url, backend

    def rpc(self, method, params=None, *, id_="1", headers=None):
        r = httpx.post(
            f"{self.proxy_url}/mock",
            json={"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}},
            headers={"X-LoopPrism-Backend": self.backend, **(headers or {})},
            timeout=10,
        )
        assert r.status_code == 200, r.text
        return r

    def call(self, tool, **kw):
        return self.rpc("tools/call", {"name": tool, "arguments": {}}, id_=tool, **kw)

    def api(self, path):
        r = httpx.get(f"{self.api_url}{path}", timeout=10)
        assert r.status_code == 200, f"{path}: {r.text}"
        return r.json()


@pytest.fixture(scope="module")
def client(stack, mock_backend):
    return Client(*stack, mock_backend)


@pytest.fixture(scope="module")
def session_run(client):
    """One MCP session: initialize, list tools, then echo / big / fail."""
    init = client.rpc("initialize")
    session = init.headers["mcp-session-id"]
    h = {"Mcp-Session-Id": session}
    client.rpc("tools/list", headers=h)
    responses = {t: client.call(t, headers=h) for t in ("echo", "big", "fail")}
    trace_id = init.headers["x-loopprism-trace-id"]
    return session, trace_id, responses


def test_services_are_up(stack):
    proxy_url, api_url = stack
    assert httpx.get(f"{proxy_url}/health").json()["status"] == "ok"
    assert httpx.get(f"{api_url}/api/health").json() == {"status": "ok"}
    dashboard = httpx.get(f"{api_url}/")
    assert dashboard.status_code == 200 and "<html" in dashboard.text.lower()


def test_responses_pass_through_unchanged(session_run):
    _, _, responses = session_run
    assert responses["echo"].json()["result"]["content"][0]["text"] == "x" * 20
    assert len(responses["big"].json()["result"]["content"][0]["text"]) == 2000
    assert responses["fail"].json()["result"]["isError"] is True


def test_session_calls_form_one_labelled_run(client, session_run):
    session, trace_id, responses = session_run
    # every response in the session carries the same run id
    assert {r.headers["x-loopprism-trace-id"] for r in responses.values()} == {trace_id}

    detail = client.api(f"/api/traces/{trace_id}")
    trace, spans = detail["trace"], detail["spans"]
    assert trace["session_id"] == session
    assert trace["correlation_source"] == "session"
    assert trace["span_count"] == 5 and trace["error_count"] == 1
    assert [s["seq"] for s in spans] == [1, 2, 3, 4, 5]
    assert [s["mcp_request_method"] for s in spans] == [
        "initialize", "tools/list", "tools/call", "tools/call", "tools/call",
    ]

    by_tool = {s["tool_name"]: s for s in spans if s["tool_name"]}
    assert by_tool["big"]["result_size_bytes"] > by_tool["echo"]["result_size_bytes"]
    assert by_tool["fail"]["status"] == "error" and by_tool["echo"]["status"] == "ok"
    assert all(s["latency_ms"] is not None and s["mcp_server_name"] == "mock" for s in spans)


def test_traceparent_names_the_run(client):
    r = client.call("echo", headers={"traceparent": TRACEPARENT})
    assert r.headers["x-loopprism-trace-id"] == TRACEPARENT_TRACE
    trace = client.api(f"/api/traces/{TRACEPARENT_TRACE}")["trace"]
    assert trace["correlation_source"] == "explicit"
    listed = {t["id"] for t in client.api("/api/traces?limit=200")["traces"]}
    assert TRACEPARENT_TRACE in listed


def test_cost_attribution_ranks_big_result_highest(client, session_run):
    _, trace_id, _ = session_run
    cost = client.api(f"/api/cost/trace/{trace_id}")
    assert cost["total_cost_usd"] > 0
    by_source = {i["source"]: i for i in cost["items"]}
    assert by_source["MCP:mock/big"]["cost_usd"] > by_source["MCP:mock/echo"]["cost_usd"]
    assert "ERROR:mock/fail" in by_source
    assert abs(sum(i["proportion"] for i in cost["items"]) - 1) < 0.01


def test_aggregate_endpoints_see_the_traffic(client, session_run):
    servers = {s["mcp_server_name"]: s for s in client.api("/api/mcp-servers")}
    assert servers["mock"]["call_count"] >= 3 and servers["mock"]["error_count"] >= 1
    tools = {t["tool_name"] for t in client.api("/api/mcp-tools")}
    assert {"echo", "big", "fail"} <= tools
    summary = client.api("/api/cost/summary")
    assert summary["total_tool_calls"] >= 4 and summary["total_errors"] >= 1
    assert client.api("/api/cost/trend")["trends"]
    assert client.api("/api/cost/top-tools")["tools"][0]["tool_name"] == "big"


def test_unknown_and_unreachable_backends(stack):
    proxy_url, _ = stack
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "x"}}
    assert httpx.post(f"{proxy_url}/nobody", json=body).status_code == 404
    dead = httpx.post(
        f"{proxy_url}/dead",
        json=body,
        headers={"X-LoopPrism-Backend": f"http://127.0.0.1:{free_port()}"},
    )
    assert dead.status_code == 502 and "error" in dead.json()


# --- agent hooks (Claude Code / Codex) -> real server ---------------------

import os  # noqa: E402
import shutil  # noqa: E402
from pathlib import Path  # noqa: E402

HOOK = Path(__file__).resolve().parent.parent / "npm" / "plugin" / "scripts" / "hook.js"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def run_hook(api_url, payload, agent, tmp_path):
    """Run the real hook script exactly as Claude Code / Codex would."""
    r = subprocess.run(
        ["node", str(HOOK), "--agent", agent],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=15,
        env={**os.environ, "LOOPPRISM_URL": api_url, "TMPDIR": str(tmp_path)},
    )
    assert (r.returncode, r.stdout) == (0, "{}"), r.stderr
    return r


@needs_node
@pytest.mark.parametrize("agent", ["claude-code", "codex"])
def test_agent_hooks_record_a_whole_run(stack, client, tmp_path, agent):
    _, api_url = stack
    sid = f"{agent}-session-1"

    def hook(event, **fields):
        run_hook(api_url, {"session_id": sid, "cwd": "/work", "hook_event_name": event, **fields}, agent, tmp_path)

    hook("SessionStart", source="startup")
    hook("UserPromptSubmit", prompt="Add a retry to the fetch helper")
    hook("PostToolUse", tool_name="Read", tool_input={"file_path": "a.py"},
         tool_response={"content": "x" * 20_000}, tool_use_id="t1", duration_ms=40)
    hook("PostToolUse", tool_name="mcp__github__create_issue", tool_input={"title": "t"},
         tool_response={"ok": True}, tool_use_id="t2", duration_ms=900)
    hook("PostToolUseFailure", tool_name="Bash", tool_input={"command": "pytest"},
         error="Exit code 1", tool_use_id="t3", duration_ms=2500)
    hook("Stop", last_assistant_message="Done")
    hook("SessionEnd", reason="other")

    traces = client.api("/api/traces?limit=200")["traces"]
    (run,) = [t for t in traces if t["session_id"] == sid]
    detail = client.api(f"/api/traces/{run['id']}")
    trace, spans = detail["trace"], detail["spans"]

    assert trace["status"] == "succeeded" and trace["ended_at"]
    assert trace["root_span_name"] == "Add a retry to the fetch helper"
    assert json.loads(trace["tags"]) == {"agent": agent}
    assert trace["span_count"] == 3 and trace["error_count"] == 1
    read, issue, bash = spans
    assert [s["seq"] for s in spans] == [1, 2, 3]
    assert (read["tool_name"], read["mcp_server_name"]) == ("Read", None)
    assert (issue["tool_name"], issue["mcp_server_name"]) == ("create_issue", "github")
    assert bash["status"] == "error" and bash["latency_ms"] == 2500
    assert read["result_size_bytes"] < 5000  # the 20 KB response was capped by the hook


@needs_node
def test_hook_does_nothing_and_does_not_fail_when_server_is_down(tmp_path):
    run_hook(f"http://127.0.0.1:{free_port()}", {"session_id": "x", "hook_event_name": "Stop"}, "codex", tmp_path)


def test_ingest_refuses_browser_origin(stack):
    _, api_url = stack
    body = {"events": [{"agent": "evil", "event": "prompt", "session_id": "web", "prompt": "x"}]}
    r = httpx.post(f"{api_url}/api/ingest/events", json=body, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    traces = httpx.get(f"{api_url}/api/traces?limit=200").json()["traces"]
    assert not [t for t in traces if t["session_id"] == "web"]
