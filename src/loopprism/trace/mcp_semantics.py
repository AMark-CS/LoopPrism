"""MCP protocol semantics parser.

Parses JSON-RPC requests to identify MCP method types, extract tool names,
arguments, and other protocol-specific metadata for tracing.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class MCPSpanType(str, Enum):
    """MCP-specific span types mapped from JSON-RPC methods."""

    # Connection lifecycle
    CLIENT_CONNECT = "mcp.client.connect"
    CLIENT_INITIALIZE = "mcp.client.initialize"
    CLIENT_DISCONNECT = "mcp.client.disconnect"

    # Server discovery
    SERVER_LIST_TOOLS = "mcp.server.list_tools"
    SERVER_LIST_PROMPTS = "mcp.server.list_prompts"
    SERVER_LIST_RESOURCES = "mcp.server.list_resources"

    # Tool execution (the most important one)
    TOOL_CALL = "mcp.tool.call"

    # Prompts & resources
    PROMPT_GET = "mcp.prompt.get"
    RESOURCE_READ = "mcp.resource.read"

    # Notifications
    NOTIFICATION = "mcp.notification"

    # Generic / unknown MCP method
    MCP_GENERIC = "mcp.generic"


# Mapping from JSON-RPC method strings to MCPSpanType
_METHOD_MAP: dict[str, MCPSpanType] = {
    "tools/call": MCPSpanType.TOOL_CALL,
    "tools/list": MCPSpanType.SERVER_LIST_TOOLS,
    "prompts/list": MCPSpanType.SERVER_LIST_PROMPTS,
    "prompts/get": MCPSpanType.PROMPT_GET,
    "resources/list": MCPSpanType.SERVER_LIST_RESOURCES,
    "resources/read": MCPSpanType.RESOURCE_READ,
    "initialize": MCPSpanType.CLIENT_INITIALIZE,
}

# Methods we care about for tracing (produce spans)
_TRACED_METHODS: set[str] = {
    "tools/call",
    "tools/list",
    "prompts/get",
    "resources/read",
    "initialize",
}


@dataclass
class ParsedMCPRequest:
    """Result of parsing an MCP JSON-RPC request.

    Attributes:
        is_mcp: Whether this looks like an MCP JSON-RPC request.
        should_trace: Whether this request should produce a span.
        span_type: The MCP span type if traceable.
        method: The JSON-RPC method string.
        request_id: JSON-RPC request ID.
        tool_name: Extracted tool name (for tools/call).
        tool_arguments: Extracted tool arguments dict (for tools/call).
        raw_body: The original parsed JSON body.
    """

    is_mcp: bool = False
    should_trace: bool = False
    span_type: Optional[MCPSpanType] = None
    method: Optional[str] = None
    request_id: Optional[str] = None
    tool_name: Optional[str] = None
    tool_arguments: Optional[dict[str, Any]] = None
    tool_call_id: Optional[str] = None
    raw_body: dict[str, Any] = field(default_factory=dict)


class MCPProtocol:
    """Parse and classify MCP JSON-RPC messages for tracing."""

    @staticmethod
    def parse(body: dict[str, Any]) -> ParsedMCPRequest:
        """Parse a JSON-RPC request body and classify it.

        Args:
            body: The parsed JSON body from the HTTP request.

        Returns:
            ParsedMCPRequest with classification results.
        """
        result = ParsedMCPRequest(raw_body=body)

        # Check if this looks like a JSON-RPC request
        if "jsonrpc" not in body and "method" not in body:
            return result  # Not JSON-RPC, not MCP

        result.is_mcp = True
        result.method = body.get("method", "")
        result.request_id = body.get("id")

        # Classify the method
        if result.method in _METHOD_MAP:
            result.span_type = _METHOD_MAP[result.method]
        elif result.method and result.method.startswith("notifications/"):
            result.span_type = MCPSpanType.NOTIFICATION
        else:
            result.span_type = MCPSpanType.MCP_GENERIC

        # Determine if we should trace
        result.should_trace = result.method in _TRACED_METHODS

        # Extract tool-specific info for tools/call
        if result.method == "tools/call":
            params = body.get("params", {})
            result.tool_name = params.get("name", "")
            result.tool_arguments = params.get("arguments", {})
            result.tool_call_id = str(result.request_id) if result.request_id else None

        # Extract tool name for tools/list response parsing
        # (we can't know tools from the request alone, this is response-side)

        return result

    @staticmethod
    def parse_response(
        body: dict[str, Any],
        request_span_type: Optional[MCPSpanType] = None,
    ) -> dict[str, Any]:
        """Extract metadata from a JSON-RPC response.

        Args:
            body: The parsed JSON-RPC response body.
            request_span_type: The span type of the corresponding request.

        Returns:
            Dict of response metadata to attach to the span.
        """
        meta: dict[str, Any] = {}

        # Check for errors
        if "error" in body:
            meta["result_is_error"] = True
            error = body["error"]
            meta["error_code"] = error.get("code")
            meta["error_message"] = error.get("message", "")

        # For tools/call response, count content items
        if request_span_type == MCPSpanType.TOOL_CALL and "result" in body:
            result = body["result"]
            if isinstance(result, dict):
                content = result.get("content", [])
                meta["content_count"] = len(content) if content else 0
                if isinstance(result.get("isError"), bool):
                    meta["result_is_error"] = result["isError"]

        # For tools/list response, count tools
        if request_span_type == MCPSpanType.SERVER_LIST_TOOLS and "result" in body:
            result = body["result"]
            if isinstance(result, dict):
                tools = result.get("tools", [])
                meta["tool_count"] = len(tools) if tools else 0

        return meta

    @staticmethod
    def method_display_name(method: str) -> str:
        """Human-readable display name for an MCP method.

        Args:
            method: The JSON-RPC method string (e.g. "tools/call").

        Returns:
            A short display name (e.g. "call").
        """
        parts = method.split("/")
        if len(parts) >= 2:
            return parts[-1]  # "call", "list", "get", etc.
        return method

    @staticmethod
    def is_connect_event(method: str) -> bool:
        """Check if this method represents a connection lifecycle event."""
        return method in ("initialize",)

    @staticmethod
    def is_notification(method: str) -> bool:
        """Check if this method is a notification (no response expected)."""
        return method.startswith("notifications/")
