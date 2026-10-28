"""Normalized session model shared by the agent adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# Event kinds, in the vocabulary of the Trajectory view.
SYSTEM = "system"
USER = "user"
CONTEXT = "context"  # injected: system reminders, CLAUDE.md, skills, hooks
ASSISTANT = "assistant"
THINKING = "thinking"
TOOL_CALL = "tool_call"
TOOL_RESULT = "tool_result"
COMPACTION = "compaction"
MODEL_CHANGE = "model_change"
SYSTEM_EVENT = "system_event"  # bookkeeping (hook summaries, ...)

MAX_EVENT_CHARS = 100_000


@dataclass
class Event:
    idx: int
    kind: str
    ts: Optional[str] = None
    turn: int = 0
    step: Optional[int] = None
    text: str = ""
    tool_name: Optional[str] = None
    tool_input: Any = None
    tool_use_id: Optional[str] = None
    is_error: bool = False
    sidechain: bool = False
    model: Optional[str] = None
    label: Optional[str] = None  # e.g. attachment type, context category

    def to_dict(self, preview: Optional[int] = None) -> dict[str, Any]:
        d = {
            "idx": self.idx,
            "kind": self.kind,
            "ts": self.ts,
            "turn": self.turn,
            "step": self.step,
            "tool_name": self.tool_name,
            "tool_use_id": self.tool_use_id,
            "is_error": self.is_error,
            "sidechain": self.sidechain,
            "model": self.model,
            "label": self.label,
            "size": len(self.text),
        }
        if self.tool_input is not None:
            d["tool_input"] = self.tool_input
        if preview is None:
            d["text"] = self.text
        else:
            d["text"] = self.text[:preview]
            d["truncated"] = len(self.text) > preview
        return d


@dataclass
class Step:
    """One model call: its usage, timing and the request it sent."""

    index: int
    turn: int
    model: str
    ts: Optional[str] = None
    end_ts: Optional[str] = None
    msg_id: Optional[str] = None
    sidechain: bool = False
    input_tokens: int = 0  # uncached
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0  # 5-minute
    cache_write_1h_tokens: int = 0
    cost_usd: Optional[float] = None
    request_ts: Optional[str] = None
    model_ms: Optional[float] = None
    thinking_ms: Optional[float] = None
    tools_ms: Optional[float] = None
    first_event: int = 0
    # Hashes of the messages this step sent (into ParsedSession.pool), when the
    # transcript records the request; None means "reconstruct from events".
    refs: Optional[list[str]] = None
    system_key: Optional[str] = None  # key into ParsedSession.shapes
    context_window: Optional[int] = None

    @property
    def total_input(self) -> int:
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens + self.cache_write_1h_tokens

    def usage(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "cache_write_1h_tokens": self.cache_write_1h_tokens,
        }


@dataclass
class SessionMeta:
    id: str
    agent: str  # "claude-code" | "codex"
    path: str
    project: Optional[str] = None  # working directory
    title: str = ""
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    models: list[str] = field(default_factory=list)
    version: Optional[str] = None
    git_branch: Optional[str] = None
    turns: int = 0
    steps: int = 0
    messages: int = 0
    tool_calls: int = 0
    size_bytes: int = 0
    cost_usd: Optional[float] = None
    fidelity: str = "estimated"  # "exact" when the real requests are recorded
    subagent_steps: int = 0

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class ParsedSession:
    meta: SessionMeta
    events: list[Event] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    # hash -> {"role", "content"}: every message any step's request contained.
    pool: dict[str, dict[str, Any]] = field(default_factory=dict)
    # shape key -> {"system": [...], "tools": [...]}
    shapes: dict[str, dict[str, Any]] = field(default_factory=dict)
    unresolved: int = 0  # request messages that could not be located
    search_text: str = ""
