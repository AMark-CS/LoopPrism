"""Shared test fixtures for loopprism."""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure src is on path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def db_path():
    """Create a temporary SQLite database path."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    yield path
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


@pytest.fixture
async def collector(db_path):
    """Create an initialized TraceCollector."""
    from loopprism.trace.collector import TraceCollector

    c = TraceCollector(db_path)
    await c.initialize()
    yield c
    await c.close()


@pytest.fixture
def mock_mcp_backend():
    """Start a mock MCP backend server.

    Returns the URL of the mock server.
    """
    import threading
    from http.server import HTTPServer, BaseHTTPRequestHandler

    class MockMCPHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length else b"{}"
            request_body = json.loads(body)

            method = request_body.get("method", "")

            if method == "tools/call":
                params = request_body.get("params", {})
                tool_name = params.get("name", "unknown")
                response = {
                    "jsonrpc": "2.0",
                    "id": request_body.get("id"),
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": f"Mock result from {tool_name}",
                            }
                        ],
                        "isError": False,
                    },
                }
            elif method == "tools/list":
                response = {
                    "jsonrpc": "2.0",
                    "id": request_body.get("id"),
                    "result": {
                        "tools": [
                            {
                                "name": "echo",
                                "description": "Echo tool",
                                "inputSchema": {"type": "object", "properties": {}},
                            },
                            {
                                "name": "search",
                                "description": "Search tool",
                                "inputSchema": {"type": "object", "properties": {}},
                            },
                        ],
                    },
                }
            elif method == "initialize":
                response = {
                    "jsonrpc": "2.0",
                    "id": request_body.get("id"),
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "serverInfo": {
                            "name": "mock-server",
                            "version": "1.0.0",
                        },
                    },
                }
            else:
                response = {
                    "jsonrpc": "2.0",
                    "id": request_body.get("id"),
                    "result": {},
                }

            response_bytes = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response_bytes)))
            self.end_headers()
            self.wfile.write(response_bytes)

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')

        def log_message(self, format, *args):
            pass  # Suppress logs

    server = HTTPServer(("127.0.0.1", 0), MockMCPHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield f"http://127.0.0.1:{port}"

    server.shutdown()
