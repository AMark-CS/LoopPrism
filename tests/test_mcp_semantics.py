"""Unit tests for MCP protocol semantics parser."""

import pytest

from loopprism.trace.mcp_semantics import (
    MCPProtocol,
    MCPSpanType,
    ParsedMCPRequest,
)


class TestMCPProtocolParse:
    """Test JSON-RPC request parsing."""

    def test_parse_tools_call(self):
        """Parse a tools/call request."""
        body = {
            "jsonrpc": "2.0",
            "id": "req-1",
            "method": "tools/call",
            "params": {
                "name": "search",
                "arguments": {"query": "test"},
            },
        }

        result = MCPProtocol.parse(body)

        assert result.is_mcp is True
        assert result.should_trace is True
        assert result.span_type == MCPSpanType.TOOL_CALL
        assert result.tool_name == "search"
        assert result.tool_arguments == {"query": "test"}
        assert result.method == "tools/call"
        assert result.request_id == "req-1"

    def test_parse_tools_list(self):
        """Parse a tools/list request."""
        body = {
            "jsonrpc": "2.0",
            "id": "req-2",
            "method": "tools/list",
            "params": {},
        }

        result = MCPProtocol.parse(body)

        assert result.is_mcp is True
        assert result.should_trace is True
        assert result.span_type == MCPSpanType.SERVER_LIST_TOOLS

    def test_parse_initialize(self):
        """Parse an initialize request."""
        body = {
            "jsonrpc": "2.0",
            "id": "req-3",
            "method": "initialize",
            "params": {},
        }

        result = MCPProtocol.parse(body)

        assert result.is_mcp is True
        assert result.should_trace is True
        assert result.span_type == MCPSpanType.CLIENT_INITIALIZE

    def test_parse_prompts_get(self):
        """Parse a prompts/get request."""
        body = {
            "jsonrpc": "2.0",
            "id": "req-4",
            "method": "prompts/get",
            "params": {"name": "greeting"},
        }

        result = MCPProtocol.parse(body)

        assert result.is_mcp is True
        assert result.should_trace is True
        assert result.span_type == MCPSpanType.PROMPT_GET

    def test_parse_notification(self):
        """Parse a notification (no response expected)."""
        body = {
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {},
        }

        result = MCPProtocol.parse(body)

        assert result.is_mcp is True
        assert result.should_trace is False  # Notifications not traced
        assert result.span_type == MCPSpanType.NOTIFICATION

    def test_parse_non_mcp(self):
        """Non JSON-RPC body should not be classified as MCP."""
        body = {"foo": "bar"}

        result = MCPProtocol.parse(body)

        assert result.is_mcp is False
        assert result.should_trace is False

    def test_parse_unknown_method(self):
        """Unknown MCP method should be classified as generic."""
        body = {
            "jsonrpc": "2.0",
            "id": "req-5",
            "method": "custom/method",
            "params": {},
        }

        result = MCPProtocol.parse(body)

        assert result.is_mcp is True
        assert result.should_trace is False  # Not in traced set
        assert result.span_type == MCPSpanType.MCP_GENERIC

    def test_method_display_name(self):
        """Test human-readable display names."""
        assert MCPProtocol.method_display_name("tools/call") == "call"
        assert MCPProtocol.method_display_name("tools/list") == "list"
        assert MCPProtocol.method_display_name("resources/read") == "read"

    def test_is_connect_event(self):
        """Test connection lifecycle detection."""
        assert MCPProtocol.is_connect_event("initialize") is True
        assert MCPProtocol.is_connect_event("tools/call") is False

    def test_is_notification(self):
        """Test notification detection."""
        assert (
            MCPProtocol.is_notification("notifications/cancelled") is True
        )
        assert MCPProtocol.is_notification("tools/call") is False


class TestMCPProtocolParseResponse:
    """Test JSON-RPC response parsing."""

    def test_parse_tool_call_response(self):
        """Parse a successful tools/call response."""
        body = {
            "jsonrpc": "2.0",
            "id": "req-1",
            "result": {
                "content": [
                    {"type": "text", "text": "hello"},
                    {"type": "text", "text": "world"},
                ],
                "isError": False,
            },
        }

        meta = MCPProtocol.parse_response(body, MCPSpanType.TOOL_CALL)

        assert meta.get("content_count") == 2
        assert meta.get("result_is_error") is False

    def test_parse_tool_call_response_error(self):
        """Parse a tools/call response with isError flag."""
        body = {
            "jsonrpc": "2.0",
            "id": "req-1",
            "result": {
                "content": [{"type": "text", "text": "Not found"}],
                "isError": True,
            },
        }

        meta = MCPProtocol.parse_response(body, MCPSpanType.TOOL_CALL)

        assert meta.get("result_is_error") is True

    def test_parse_jsonrpc_error(self):
        """Parse a JSON-RPC error response."""
        body = {
            "jsonrpc": "2.0",
            "id": "req-1",
            "error": {
                "code": -32600,
                "message": "Invalid Request",
            },
        }

        meta = MCPProtocol.parse_response(body, MCPSpanType.TOOL_CALL)

        assert meta.get("result_is_error") is True
        assert meta.get("error_code") == -32600

    def test_parse_tools_list_response(self):
        """Parse a tools/list response and count tools."""
        body = {
            "jsonrpc": "2.0",
            "id": "req-2",
            "result": {
                "tools": [
                    {"name": "echo"},
                    {"name": "search"},
                    {"name": "read_file"},
                ],
            },
        }

        meta = MCPProtocol.parse_response(
            body,
            MCPSpanType.SERVER_LIST_TOOLS,
        )

        assert meta.get("tool_count") == 3
