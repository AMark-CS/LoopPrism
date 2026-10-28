"""Read-only inspection of coding-agent session files (Claude Code, Codex).

Parsers turn each agent's on-disk transcript into one normalized
``ParsedSession``: events (the trajectory), steps (one per model call, with
exact token usage) and, where the transcript allows it, the exact request each
step sent. ``store.SessionStore`` indexes them for listing and search, and
``context`` breaks each step's input into categories.
"""

from .models import Event, ParsedSession, SessionMeta, Step

__all__ = ["Event", "ParsedSession", "SessionMeta", "Step"]
