"""Made-up DeepSeek Harness and WorkBuddy sessions in their native formats, for tests and smoke tests.

    python tests/support_other_agents.py /tmp/lp-others    # writes /tmp/lp-others/.dsh/... and .workbuddy/...
    DSH_HOME=/tmp/lp-others/.dsh WORKBUDDY_CONFIG_DIR=/tmp/lp-others/.workbuddy lprism proxy
"""

from __future__ import annotations

import json
import os
import sys

import zstandard

T0 = 1_786_974_941_000  # ms


def jl(rows):
    return "".join(json.dumps(r) + "\n" for r in rows)


def frames(rows, per_frame=3):
    """zstd-compress rows as independent frames, the way dsh appends them."""
    out = b""
    for i in range(0, len(rows), per_frame):
        out += zstandard.ZstdCompressor().compress(jl(rows[i : i + per_frame]).encode())
    return out


# ------------------------------------------------------------------------ dsh
def dsh_rows():
    msg = lambda role, content, **kw: {"role": role, "content": content, **kw}  # noqa: E731
    return [
        {"type": "session", "version": 4, "id": "session-abc", "createdAt": T0, "cwd": "/work/app"},
        {"type": "request/context", "seq": 1, "time": T0, "data": {"provider": "deepseek", "model": "deepseek-v4-flash", "contextWindow": 1000000}},
        {"type": "request/header", "seq": 2, "time": T0, "data": {"header": {
            "config": {"model": "deepseek-v4-flash"}, "system": "You are dsh. " * 40,
            "tools": [{"name": "bash", "description": "Run a command", "parameters": {"type": "object"}}]}, "reason": "initial"}},
        # an injected runtime snapshot from a plugin, then what the user typed
        {"type": "user/message", "seq": 3, "time": T0 + 1, "surfaceOp": "append", "data": {
            "id": "u0", "role": "user", "source": {"kind": "plugin", "plugin": "user-approval"},
            "content": [{"type": "text", "text": "The approval policy changed."}]}},
        {"type": "user/message", "seq": 4, "time": T0 + 2, "surfaceOp": "append", "data": {
            "id": "u1", "role": "user", "source": {"kind": "user"}, "content": [{"type": "text", "text": "Fix the parser"}]}},
        {"type": "step/start", "seq": 5, "time": T0 + 10, "data": {"turn": 1, "step": 1}},
        {"type": "assistant/chunk", "seq": 6, "time": T0 + 11, "data": {"turn": 1, "step": 1, "chunk": {"type": "text-delta"}}},
        {"type": "assistant/message", "seq": 7, "time": T0 + 3010, "surfaceOp": "append", "data": {"turn": 1, "step": 1,
            "message": {"id": "a1", "role": "assistant", "source": {"kind": "model", "model": "deepseek-v4-flash"}, "content": [
                {"type": "reasoning", "text": "I should look at the file."},
                {"type": "text", "text": "Let me read it."},
                {"type": "tool-call", "id": "call1", "name": "bash", "arguments": "{\"command\": \"cat parser.py\"}"}]},
            "usage": {"inputTokens": 800, "outputTokens": 60, "cacheReadTokens": 5000, "reasoningTokens": 20}}},
        {"type": "tool/call", "seq": 8, "time": T0 + 3011, "data": {"turn": 1, "step": 1, "callId": "call1", "name": "bash", "arguments": "{}"}},
        # real dsh shape: the result is a tool-result part inside the message
        {"type": "tool/result", "seq": 9, "time": T0 + 4011, "surfaceOp": "append", "data": {"turn": 1, "step": 1, "message": {
            "id": "r1", "role": "tool", "source": {"kind": "tool", "callId": "call1"}, "content": [
                {"type": "tool-result", "toolCallId": "call1", "isError": False, "content": [{"type": "text", "text": "def parse(): pass"}]}]}}},
        {"type": "step/start", "seq": 10, "time": T0 + 4020, "data": {"turn": 1, "step": 2}},
        # a model-only trimmed copy of the result must not replace the full one
        {"type": "tool/result", "seq": 11, "time": T0 + 4025, "surfaceOp": {"op": "replace", "startSeq": 9, "endSeq": 9}, "data": {"message": {
            "id": "r1", "toolCallId": "call1", "content": [{"type": "text", "text": "trimmed"}]}}},
        {"type": "assistant/message", "seq": 12, "time": T0 + 6020, "surfaceOp": "append", "data": {"turn": 1, "step": 2,
            "message": {"id": "a2", "role": "assistant", "source": {"model": "deepseek-v4-flash"}, "content": [{"type": "text", "text": "Fixed."}]},
            "usage": {"inputTokens": 100, "outputTokens": 10, "cacheReadTokens": 5800}}},
        {"type": "assistant/message", "seq": 13, "time": T0 + 6021, "data": {"message": {"id": "a2", "content": [{"type": "text", "text": "Duplicate"}]}}},
        {"type": "session/title", "seq": 14, "time": T0 + 6030, "data": {"title": "Parser fix"}},
        # a compaction summary: the model-visible replacement of the earlier turns
        {"type": "user/message", "seq": 15, "time": T0 + 7000, "surfaceOp": {"op": "replace", "startSeq": 1, "endSeq": 12}, "data": {
            "id": "sum", "content": [{"type": "text", "text": "Summary of the work so far"}]}},
    ]


def wb_rows():
    base = {"sessionId": "s-1", "cwd": "/work/app"}
    pd = lambda mid, **kw: {"messageId": mid, "model": "deepseek-v4.1-flash", "requestModelName": "Deepseek-V4.1-Flash", "agent": "cli", **kw}  # noqa: E731
    raw = lambda p, c, hit: {"prompt_tokens": p, "completion_tokens": c, "prompt_cache_hit_tokens": hit, "credit": 0.1}  # noqa: E731
    return [
        {"type": "message", "role": "user", "id": "u1", "timestamp": T0, "providerData": {"agent": "cli"}, "content": [{
            "type": "input_text",
            "text": '<system-reminder data-role="user-context"><user_info>OS: darwin</user_info></system-reminder>'
                    "<user_query>Fix the parser</user_query>"}], **base},
        {"type": "reasoning", "id": "r1", "parentId": "u1", "timestamp": T0 + 2000, "providerData": pd("m1"), "content": [],
         "rawContent": [{"type": "reasoning_text", "text": "Look at the file first."}], **base},
        {"type": "message", "role": "assistant", "id": "m1", "timestamp": T0 + 2100, "status": "completed",
         "content": [{"type": "output_text", "text": "Let me read it."}], "providerData": pd("m1"), **base},
        # two tool calls of one response: the usage sits on the first
        {"type": "function_call", "id": "f1", "callId": "c1", "name": "Read", "arguments": "{\"file_path\": \"parser.py\"}",
         "timestamp": T0 + 2200, "providerData": pd("m1", rawUsage=raw(1000, 50, 800)), **base},
        {"type": "function_call", "id": "f2", "callId": "c2", "name": "Bash", "arguments": "{\"command\": \"ls\"}",
         "timestamp": T0 + 2201, "providerData": pd("m1"), **base},
        {"type": "function_call_result", "id": "x1", "callId": "c1", "name": "Read", "status": "completed",
         "output": {"type": "text", "text": "def parse(): pass"}, "timestamp": T0 + 3200, "providerData": pd("m1"), **base},
        {"type": "function_call_result", "id": "x2", "callId": "c2", "name": "Bash", "status": "failed",
         "output": [{"type": "text", "text": "boom"}], "timestamp": T0 + 3300, "providerData": pd("m1"), **base},
        # the closing message: usage in providerData.rawUsage and in message.usage (the same numbers)
        {"type": "message", "role": "assistant", "id": "m2", "timestamp": T0 + 6000, "status": "completed",
         "content": [{"type": "output_text", "text": "Fixed it."}],
         "providerData": pd("m2", rawUsage=raw(1500, 30, 1400)),
         "message": {"usage": {"input_tokens": 1500, "output_tokens": 30, "cache_read_input_tokens": 1400}}, **base},
        {"type": "message", "role": "assistant", "id": "e1", "timestamp": T0 + 6100, "content": [],
         "providerData": {"agent": "cli", "error": "rate limited", "skipRun": True}, **base},
        {"type": "message", "role": "user", "id": "u2", "timestamp": T0 + 7000, "content": [{"type": "input_text", "text": "Summary so far"}],
         "providerData": {"agent": "cli", "isSummary": True, "isCompacted": True}, **base},
        {"type": "ai-title", "timestamp": T0 + 7100, "aiTitle": "Parser fix", **base},
        {"type": "file-history-snapshot", "id": "h", "timestamp": T0 + 7200, "isSnapshotUpdate": False, "snapshot": {}, "cwd": "/work/app"},
    ]




def write(base: str) -> dict[str, str]:
    """Write one session per agent under ``base``; returns their paths."""
    d = os.path.join(base, ".dsh", "sessions", "--work-app--", "session-abc")
    os.makedirs(d, exist_ok=True)
    dsh_path = os.path.join(d, "session.v4.jsonl.zstd")
    with open(dsh_path, "wb") as fh:
        fh.write(frames(dsh_rows()))
    w = os.path.join(base, ".workbuddy", "projects", "Users-demo-app")
    os.makedirs(w, exist_ok=True)
    wb_path = os.path.join(w, "s-1.jsonl")
    with open(wb_path, "w") as fh:
        fh.write(jl(wb_rows()))
    return {"dsh": dsh_path, "workbuddy": wb_path}


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/lp-others"
    print(json.dumps(write(out), indent=2))
    print(f"DSH_HOME={out}/.dsh WORKBUDDY_CONFIG_DIR={out}/.workbuddy lprism proxy")
