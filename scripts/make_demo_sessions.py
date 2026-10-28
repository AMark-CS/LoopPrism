#!/usr/bin/env python3
"""Generate a made-up ~/.claude + ~/.codex so the session inspector can be shown
(README screenshots, demos) without exposing anyone's real sessions.

    python scripts/make_demo_sessions.py /tmp/lp-demo
    CLAUDE_CONFIG_DIR=/tmp/lp-demo/.claude CODEX_HOME=/tmp/lp-demo/.codex lprism proxy

Everything is synthetic and deterministic (seeded).
"""

from __future__ import annotations

import json
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from loopprism.sessions.claude_code import message_hash  # noqa: E402
from loopprism.sessions.tokens import estimate_text  # noqa: E402

FILES = [
    "src/payments/webhook.py", "src/payments/retry.py", "tests/test_webhook.py", "src/api/middleware.py",
    "src/api/routes.py", "src/settings/models.py", "web/src/Settings.tsx", "web/src/theme.ts",
    "src/auth/session.py", "docs/architecture.md", "pyproject.toml", "src/db/migrations/0042_add_limits.py",
]
SNIPPET = (
    "def handle_event(event, *, db, clock=time.time):\n"
    "    \"\"\"Apply one webhook event exactly once.\"\"\"\n"
    "    key = f\"{event['id']}:{event['type']}\"\n"
    "    with db.transaction() as tx:\n"
    "        if tx.seen(key):\n"
    "            return Result.ignored(key)\n"
    "        handler = HANDLERS.get(event['type'])\n"
    "        if handler is None:\n"
    "            raise UnknownEvent(event['type'])\n"
    "        out = handler(event, tx=tx, now=clock())\n"
    "        tx.mark_seen(key)\n"
    "        return out\n"
)


def iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def lines_of(n: int, rng: random.Random) -> str:
    out = []
    for i in range(n):
        out.append(f"{i + 1:>4}  " + rng.choice(SNIPPET.splitlines()))
    return "\n".join(out)


class Clock:
    def __init__(self, start: datetime) -> None:
        self.t = start

    def tick(self, lo: float, hi: float, rng: random.Random) -> datetime:
        self.t += timedelta(seconds=rng.uniform(lo, hi))
        return self.t


def write(path: str, rows: list[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def claude_session(root: str, project: str, title: str, prompts: list[str], model: str, steps_per_turn: int,
                   start: datetime, seed: int, exact: bool = True, loop: bool = False) -> None:
    rng = random.Random(seed)
    sid = str(uuid.UUID(int=rng.getrandbits(128)))
    clock = Clock(start)
    cwd = f"/Users/demo/{project}"
    folder = os.path.join(root, "projects", cwd.replace("/", "-"))
    system_text = "You are Claude Code, Anthropic's official CLI for Claude.\n" + "Follow the project conventions. " * 420
    tools = [
        {"name": n, "description": f"{n} tool. " + "Use this to work with the repository. " * 28,
         "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "pattern": {"type": "string"}}}}
        for n in ["Read", "Edit", "Write", "Bash", "Grep", "Glob", "Agent", "WebFetch", "TodoWrite", "NotebookEdit"] * 4
    ][:40]
    shape = {"system": [{"type": "text", "text": system_text}], "tools": tools}
    sys_tok = estimate_text(system_text) * 1.35
    tool_tok = sum(estimate_text(json.dumps(t)) for t in tools) * 1.35
    ctx_blob = {"role": "system", "content": [{"type": "text", "text": "<system-reminder>\n# Project instructions (CLAUDE.md)\n" + "Run the test-suite before committing. " * 60 + "\n</system-reminder>"}]}

    rows: list[dict] = [{"type": "custom-title", "customTitle": title, "sessionId": sid}]
    if exact:
        rows.append({"type": "api-request-shape", "sessionId": sid, "shapeHash": "shape1", "shape": shape})
        rows.append({"type": "api-request-blob", "sessionId": sid, "hash": message_hash(ctx_blob), "message": ctx_blob})
    hashes: list[str] = []
    prev_req: dict | None = None
    prev_total = 0
    msg_tokens = estimate_text(ctx_blob["content"][0]["text"]) * 1.35
    n_req = 0
    msg_id = 0
    first = True
    failing = 0

    def common(extra: dict) -> dict:
        return {"sessionId": sid, "cwd": cwd, "version": "2.1.308" if exact else "2.1.150", "gitBranch": "main", **extra}

    for turn, prompt in enumerate(prompts):
        t = clock.tick(20, 240, rng)
        pm = {"role": "user", "content": prompt}
        rows.append(common({"type": "user", "uuid": str(uuid.uuid4()), "timestamp": iso(t), "message": pm}))
        msg_tokens += estimate_text(prompt) * 1.35
        new_msgs = [pm, ctx_blob] if turn == 0 else [pm]
        for k in range(steps_per_turn + rng.randint(-2, 3)):
            n_req += 1
            msg_id += 1
            req_t = clock.tick(0.1, 0.6, rng)
            req_hashes = hashes + [message_hash(m) for m in new_msgs]
            if exact:
                rows.append({"type": "api-request", "sessionId": sid, "id": f"req{n_req}", "timestamp": iso(req_t),
                             "shapeHash": "shape1", "base": prev_req and prev_req["id"], "keep": len(hashes),
                             "tail": [message_hash(m) for m in new_msgs], "params": {"model": model}})
                prev_req = {"id": f"req{n_req}"}
            total_in = int(sys_tok + tool_tok + msg_tokens)
            fresh = max(200, int(total_in - prev_total))
            usage = {
                "input_tokens": 6 + rng.randint(0, 40),
                "output_tokens": 0,
                "cache_read_input_tokens": prev_total if not first else 0,
                "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": fresh if not first else total_in},
            }
            first = False
            prev_total = total_in
            last_step_of_turn = k == steps_per_turn - 1
            blocks: list[dict] = [{"type": "thinking", "thinking": "", "signature": "S" * rng.randint(300, 900)}]
            if last_step_of_turn:
                text = rng.choice([
                    "Done. The change is in place and the test-suite passes; I kept the diff small.",
                    "That fixes it: the handler now de-duplicates on the event id before applying side effects.",
                    "I traced the failure to the retry path and fixed it. Summary of the changes is above.",
                ])
                blocks.append({"type": "text", "text": text})
            else:
                tool = rng.choice(["Read", "Read", "Grep", "Edit", "Bash", "Glob"])
                fp = rng.choice(FILES)
                inp = {"Read": {"file_path": fp}, "Grep": {"pattern": "handle_event", "path": "src"},
                       "Edit": {"file_path": fp, "old_string": "retry(3)", "new_string": "retry(3, jitter=True)"},
                       "Bash": {"command": "pytest -x -q tests/test_webhook.py"}, "Glob": {"pattern": "src/**/*.py"}}[tool]
                if loop and 8 < n_req < 15:
                    tool, inp = "Bash", {"command": "pytest -x -q tests/test_webhook.py"}
                blocks.append({"type": "text", "text": f"Let me look at {fp}."} if rng.random() < 0.5 else {"type": "text", "text": ""})
                blocks[-1] = blocks[-1] if blocks[-1]["text"] else {"type": "text", "text": "Checking the next piece."}
                tool_id = f"toolu_{n_req:04d}"
                blocks.append({"type": "tool_use", "id": tool_id, "name": tool, "input": inp})
            out_tok = int(estimate_text(json.dumps(blocks)) * 1.35) + rng.randint(80, 600)
            usage["output_tokens"] = out_tok
            am = {"role": "assistant", "content": blocks}
            end_t = clock.tick(2.0, 11.0, rng)
            mid = f"msg_{msg_id:06d}"
            for b in blocks:
                rows.append(common({"type": "assistant", "uuid": str(uuid.uuid4()), "timestamp": iso(end_t),
                                    "thinkingDurationMs": rng.randint(600, 3500) if b["type"] == "thinking" else None,
                                    "message": {"id": mid, "model": model, "role": "assistant", "usage": usage, "content": [b]}}))
            msg_tokens += out_tok
            hashes = req_hashes + [message_hash(am)]
            if last_step_of_turn:
                new_msgs = []
                break
            if exact is False:
                pass
            res_text = lines_of(rng.randint(8, 160), rng)
            is_err = bool(loop and 8 < n_req < 15)
            if is_err:
                res_text = "FAILED tests/test_webhook.py::test_replay - AssertionError: expected 1 charge, got 2"
            rm = {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_id, "content": res_text, "is_error": is_err}]}
            tool_t = clock.tick(0.2, 4.5, rng)
            rows.append(common({"type": "user", "uuid": str(uuid.uuid4()), "timestamp": iso(tool_t), "message": rm}))
            msg_tokens += estimate_text(res_text) * 1.35
            new_msgs = [am, rm]
            hashes = req_hashes
    write(os.path.join(folder, f"{sid}.jsonl"), rows)


def codex_session(root: str, project: str, prompts: list[str], model: str, steps_per_turn: int, start: datetime, seed: int) -> None:
    rng = random.Random(seed)
    sid = str(uuid.UUID(int=rng.getrandbits(128)))
    clock = Clock(start)
    day = start.strftime("%Y/%m/%d")
    path = os.path.join(root, "sessions", day, f"rollout-{start.strftime('%Y-%m-%dT%H-%M-%S')}-{sid}.jsonl")
    cwd = f"/Users/demo/{project}"
    rows = [{"type": "session_meta", "timestamp": iso(start), "payload": {"id": sid, "cwd": cwd, "cli_version": "0.164.0", "timestamp": iso(start)}}]
    rows.append({"type": "response_item", "timestamp": iso(start), "payload": {"type": "additional_tools", "tools": [
        {"name": f"tool_{i}", "description": "Run a command or edit files. " * 25} for i in range(14)]}})
    rows.append({"type": "response_item", "timestamp": iso(start), "payload": {"type": "message", "role": "developer",
                 "content": [{"type": "input_text", "text": "You are Codex, a coding agent. " * 220}]}})
    total = 7_500
    n = 0
    for turn, prompt in enumerate(prompts):
        tid = f"turn-{turn}"
        rows.append({"type": "turn_context", "timestamp": iso(clock.tick(10, 90, rng)), "payload": {"turn_id": tid, "model": model}})
        rows.append({"type": "response_item", "timestamp": iso(clock.t), "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": prompt}]}})
        total += estimate_text(prompt)
        for k in range(steps_per_turn):
            n += 1
            last = k == steps_per_turn - 1
            if last:
                rows.append({"type": "response_item", "timestamp": iso(clock.tick(2, 9, rng)), "payload": {"type": "message", "role": "assistant",
                             "content": [{"type": "output_text", "text": "All set — the settings page now uses the shared Card and Toggle components."}]}})
            else:
                cid = f"call{n}"
                rows.append({"type": "response_item", "timestamp": iso(clock.tick(2, 9, rng)), "payload": {"type": "function_call", "name": "shell", "call_id": cid,
                             "arguments": json.dumps({"cmd": rng.choice(["rg -n Settings web/src", "sed -n 1,120p web/src/Settings.tsx", "npm test -- Settings"])})}})
            out = rng.randint(60, 700)
            rows.append({"type": "token_usage_record", "timestamp": iso(clock.t), "ordinal": n, "payload": {
                "turn_id": tid, "root_turn_id": tid, "response_id": f"resp{n}",
                "usage": {"input_tokens": int(total), "cached_input_tokens": int(total * 0.93), "output_tokens": out}}})
            rows.append({"type": "event_msg", "timestamp": iso(clock.t), "payload": {"type": "token_count", "info": {"model_context_window": 258400}}})
            total += out
            if not last:
                res = lines_of(rng.randint(10, 120), rng)
                rows.append({"type": "response_item", "timestamp": iso(clock.tick(0.3, 5, rng)), "payload": {"type": "function_call_output", "call_id": cid, "output": res}})
                total += estimate_text(res)
    write(path, rows)


def main(dest: str) -> None:
    now = datetime.now(timezone.utc)
    claude_root = os.path.join(dest, ".claude")
    codex_root = os.path.join(dest, ".codex")
    claude_session(claude_root, "acme-api", "Fix flaky checkout webhook test", [
        "The test_replay webhook test fails about one run in five. Find out why and fix it.",
        "Good. Can you also make the retry path idempotent?",
        "Add a regression test for the double-charge case.",
        "Run the full suite and summarize what changed.",
    ], "claude-sonnet-5-5", 11, now - timedelta(minutes=50), 1, loop=True)
    claude_session(claude_root, "acme-api", "Add rate limiting to the public API", [
        "Add per-key rate limiting to the public API. Use the existing Redis connection.",
        "Return 429 with a Retry-After header, and document it in docs/architecture.md.",
        "Add a migration for the new limits table.",
    ], "claude-opus-5-5", 14, now - timedelta(hours=5), 2)
    claude_session(claude_root, "web-dashboard", "Explain the auth middleware", [
        "Walk me through how the auth middleware decides a session is valid.",
        "What happens when the refresh token is revoked?",
    ], "claude-haiku-4-5", 5, now - timedelta(days=1, hours=2), 3, exact=False)
    claude_session(claude_root, "web-dashboard", "Migrate the settings page to the new design system", [
        "Port web/src/Settings.tsx to the new Card and Toggle components and keep the tests green.",
        "Also move the theme tokens out of theme.ts.",
    ], "claude-sonnet-5-5", 9, now - timedelta(days=2), 4)
    codex_session(codex_root, "web-dashboard", [
        "Migrate the settings page to the shared design-system components.",
        "Now update the snapshot tests.",
    ], "gpt-6.1-sol", 10, now - timedelta(hours=3), 5)
    codex_session(codex_root, "acme-api", ["Summarize the open TODOs in src/payments."], "gpt-6.1-terra", 6, now - timedelta(days=3), 6)
    print(f"wrote demo sessions to {dest}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/lp-demo")
