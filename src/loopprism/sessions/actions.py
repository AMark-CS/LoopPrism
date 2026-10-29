"""Things you can do to a session: resume it, export it, move it to the Trash."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from . import models as M
from .models import ParsedSession, SessionMeta

SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{6,80}$")


def resume_command(meta: SessionMeta) -> str:
    """The shell command that resumes this session, including the cd."""
    # A Codex history page is listed as "<session>_<thread>"; resuming takes the session.
    if meta.agent not in ("claude-code", "codex"):
        raise ValueError(f"{meta.agent} sessions are resumed from their own app")
    rid = meta.id if meta.agent == "claude-code" else meta.id.split("_", 1)[0]
    if not SAFE_ID.match(rid):
        raise ValueError("unexpected session id")
    cmd = f"claude --resume {rid}" if meta.agent == "claude-code" else f"codex resume {rid}"
    if meta.project and os.path.isdir(meta.project):
        if sys.platform == "win32":  # cmd.exe: `cd /d` also switches drive
            return f"cd /d {subprocess.list2cmdline([meta.project])} && {cmd}"
        return f"cd {shlex.quote(meta.project)} && {cmd}"
    return cmd


def open_in_terminal(command: str) -> None:
    """Run a command in a new terminal window (macOS Terminal, a Windows console)."""
    if sys.platform == "win32":
        # A string (not a list) so cmd.exe sees the quotes in `cd /d "..."` as written.
        subprocess.Popen(f"cmd.exe /k {command}", creationflags=subprocess.CREATE_NEW_CONSOLE)
        return
    if sys.platform != "darwin":
        raise RuntimeError("Opening a terminal is only supported on macOS and Windows")
    escaped = command.replace("\\", "\\\\").replace('"', '\\"')
    script = f'tell application "Terminal"\nactivate\ndo script "{escaped}"\nend tell'
    subprocess.run(["osascript", "-e", script], check=True, timeout=15)


def _recycle_windows(real: Path) -> str:
    """Send the session file (and its sibling folder) to the Recycle Bin."""
    script = (
        "Add-Type -AssemblyName Microsoft.VisualBasic;"
        "$f=[Microsoft.VisualBasic.FileIO.FileSystem];"
        "$p=$env:LP_RECYCLE_FILE; $d=$env:LP_RECYCLE_DIR;"
        "$f::DeleteFile($p,'OnlyErrorDialogs','SendToRecycleBin');"
        "if ($d) { $f::DeleteDirectory($d,'OnlyErrorDialogs','SendToRecycleBin') }"
    )
    sibling = real.with_suffix("")
    # Paths travel in the environment, never spliced into the script text.
    env = {**os.environ, "LP_RECYCLE_FILE": str(real), "LP_RECYCLE_DIR": str(sibling) if sibling.is_dir() else ""}
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        env=env, check=True, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return "Recycle Bin"


def trash(path: str, allowed_roots: list[str]) -> str:
    """Move a session file (and its sibling folder) to the Trash.

    Only paths inside the agents' own session folders can be removed.
    """
    real = Path(path).resolve()
    if not any(real.is_relative_to(Path(r).resolve()) for r in allowed_roots if r):
        raise PermissionError("Not inside a known session folder")
    if real.suffix != ".jsonl" or not real.is_file():
        raise FileNotFoundError(str(real))
    if sys.platform == "win32":
        return _recycle_windows(real)
    if sys.platform != "darwin":
        raise RuntimeError("Moving sessions to the Trash is supported on macOS and Windows")
    trash_dir = Path.home() / ".Trash"
    trash_dir.mkdir(parents=True, exist_ok=True)

    def unique(name: str) -> Path:
        dest = trash_dir / name
        n = 1
        while dest.exists():
            dest = trash_dir / f"{Path(name).stem} {n}{Path(name).suffix}"
            n += 1
        return dest

    dest = unique(real.name)
    shutil.move(str(real), str(dest))
    sibling = real.with_suffix("")
    if sibling.is_dir():  # Claude Code keeps per-session files in a folder of the same name
        shutil.move(str(sibling), str(unique(sibling.name)))
    return str(dest)


def export_markdown(ps: ParsedSession) -> str:
    m = ps.meta
    agent = {"claude-code": "Claude Code", "codex": "Codex", "dsh": "DeepSeek Harness", "workbuddy": "WorkBuddy", "opencode": "OpenCode", "gemini": "Gemini CLI", "cursor": "Cursor"}.get(m.agent, m.agent)
    lines = [f"# {m.title}", "", f"- Agent: {agent}", f"- Session: `{m.id}`"]
    if m.project:
        lines.append(f"- Project: `{m.project}`")
    if m.started_at:
        lines.append(f"- Started: {m.started_at}")
    if m.models:
        lines.append(f"- Models: {', '.join(m.models)}")
    if m.cost_usd is not None:
        lines.append(f"- Estimated API cost: ${m.cost_usd:.2f}")
    lines.append("")
    turn = 0
    for e in ps.events:
        if e.sidechain:
            continue
        if e.kind == M.USER:
            turn += 1
            lines += [f"## Turn {turn}", "", "**User**", "", e.text.strip(), ""]
        elif e.kind == M.ASSISTANT:
            lines += ["**Assistant**", "", e.text.strip(), ""]
        elif e.kind == M.TOOL_CALL:
            arg = ""
            if isinstance(e.tool_input, dict):
                arg = e.tool_input.get("command") or e.tool_input.get("file_path") or e.tool_input.get("path") or e.tool_input.get("pattern") or ""
            lines.append(f"- `{e.tool_name}` {arg if not isinstance(arg, (dict, list)) else ''}".rstrip())
    return "\n".join(lines).strip() + "\n"
