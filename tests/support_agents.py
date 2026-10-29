"""A made-up Claude Code session with subagents, for tests and demos.

    python tests/support_agents.py /tmp/lp-agents      # writes /tmp/lp-agents/.claude/projects/...

Shape: the main agent spawns ``Explore`` (a, short) and ``code-review`` (b, long,
runs in parallel with a); ``code-review`` spawns ``test-runner`` (c). A fourth
spawn (d) was never linked to an agent file.
"""

from __future__ import annotations

import json
import os
import sys

SID = "aaaaaaaa-1111-2222-3333-444444444444"
A, B, C = "aexplore0001", "breview00001", "ctester00001"
MODEL = "claude-sonnet-5-5"
PROJECT = "-work-app"


# LP_DEMO_SCALE multiplies every token count, so a demo (README screenshots) shows realistic
# costs instead of "<$0.01". Tests leave it at 1.
SCALE = int(os.environ.get("LP_DEMO_SCALE", "1"))


def u(inp=100, out=40, read=2000):
    inp, out, read = inp * SCALE, out * SCALE, read * SCALE
    return {"input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": read,
            "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0}}


def t(sec: int) -> str:
    h, rem = divmod(600 + sec, 3600)  # 10:00:00 + sec
    m, s = divmod(rem, 60)
    return f"2026-10-28T{10 + h - 0:02d}:{m:02d}:{s:02d}.000Z" if h else f"2026-10-28T10:{m:02d}:{s:02d}.000Z"


def user(text, sec, **kw):
    return {"type": "user", "uuid": f"u{sec}{len(text)}", "timestamp": t(sec), "cwd": "/work/app", "sessionId": SID,
            "message": {"role": "user", "content": text}, **kw}


def result(tool_use_id, text, sec, agent_id=None, **kw):
    row = {"type": "user", "uuid": f"r{tool_use_id}", "timestamp": t(sec), "sessionId": SID,
           "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": text}]}, **kw}
    if agent_id:
        row["toolUseResult"] = {"agentId": agent_id}
    return row


def assistant(mid, sec, blocks, usage=None, **kw):
    return {"type": "assistant", "uuid": f"a{mid}", "timestamp": t(sec), "sessionId": SID,
            "message": {"id": mid, "model": MODEL, "role": "assistant", "usage": usage or u(), "content": blocks}, **kw}


def spawn(tool_id, description, prompt, kind, background=False):
    return {"type": "tool_use", "id": tool_id, "name": "Agent",
            "input": {"description": description, "prompt": prompt, "subagent_type": kind, "run_in_background": background}}


def notification(agent_id, tool_id, sec, tokens, tools, ms):
    body = (f"<task-notification>\n<task-id>{agent_id}</task-id>\n<tool-use-id>{tool_id}</tool-use-id>\n"
            f"<status>completed</status>\n<usage><subagent_tokens>{tokens}</subagent_tokens><tool_uses>{tools}</tool_uses>"
            f"<duration_ms>{ms}</duration_ms></usage>\n</task-notification>")
    return {"type": "queue-operation", "operation": "enqueue", "timestamp": t(sec), "sessionId": SID, "content": body}


def sub(agent_id, rows):
    for r in rows:
        r["isSidechain"] = True
        r["agentId"] = agent_id
    return rows


def write(root) -> str:
    """Write the session under ``root/.claude/projects``; returns the main file's path."""
    proj = os.path.join(str(root), ".claude", "projects", PROJECT)
    os.makedirs(os.path.join(proj, SID, "subagents"), exist_ok=True)
    main = [
        {"type": "custom-title", "customTitle": "Refactor payments", "sessionId": SID},
        user("Refactor the payments retry logic and update the docs", 0, version="2.1.310"),
        assistant("m1", 5, [
            spawn("toolu_A", "Map the repo", "Find where payment retries live.", "Explore"),
            spawn("toolu_B", "Review payments diff", "Review src/payments for correctness.", "code-review", True),
            spawn("toolu_D", "Write release notes", "Draft release notes.", "general-purpose"),
        ]),
        result("toolu_A", f"Found it.\nagentId: {A} (internal)", 50, A),
        result("toolu_B", f"Async agent launched.\nagentId: {B}", 12, B),
        notification(B, "toolu_B", 200, 71000, 9, 188000),
        assistant("m2", 210, [{"type": "text", "text": "All done."}]),
    ]
    with open(os.path.join(proj, f"{SID}.jsonl"), "w") as fh:
        fh.write("\n".join(json.dumps(r) for r in main) + "\n")

    files = {
        A: sub(A, [
            user("Find where payment retries live.", 10),
            assistant("x1", 20, [{"type": "tool_use", "id": "tA1", "name": "Grep", "input": {"pattern": "retry"}}], u(50, 20, 500)),
            result("tA1", "src/payments/retry.py:12", 25),
            assistant("x2", 48, [{"type": "text", "text": "Retries are in src/payments/retry.py."}], u(60, 30, 800)),
        ]),
        B: sub(B, [
            user("Review src/payments for correctness.", 12),
            assistant("y1", 60, [spawn("toolu_C", "Run the tests", "Run pytest tests/test_webhook.py", "test-runner")], u(300, 80, 4000)),
            result("toolu_C", f"3 failed.\nagentId: {C}", 111, C),
            assistant("y2", 130, [{"type": "tool_use", "id": "tB1", "name": "Read", "input": {"file_path": "retry.py"}}], u(400, 90, 6000)),
            result("tB1", "boom", 135, is_error=True) | {"message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "tB1", "content": "boom", "is_error": True}]}},
            assistant("y3", 198, [{"type": "text", "text": "Three issues: unbounded retry, no idempotency key, swallowed timeout."}], u(500, 120, 8000)),
        ]),
        C: sub(C, [
            user("Run pytest tests/test_webhook.py", 60),
            assistant("z1", 100, [{"type": "tool_use", "id": "tC1", "name": "Bash", "input": {"command": "pytest"}}], u(80, 30, 900)),
            result("tC1", "3 failed, 18 passed", 108),
            assistant("z2", 110, [{"type": "text", "text": "3 failed, 18 passed."}], u(90, 20, 1000)),
        ]),
    }
    for aid, rows in files.items():
        with open(os.path.join(proj, SID, "subagents", f"agent-{aid}.jsonl"), "w") as fh:
            fh.write("\n".join(json.dumps(r) for r in rows) + "\n")
    return os.path.join(proj, f"{SID}.jsonl")


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/lp-agents"
    print(write(out))
    print(f"CLAUDE_CONFIG_DIR={out}/.claude lprism proxy")
