"""Cheap token estimates; real counts come from the model's reported usage."""

from __future__ import annotations

import json
from typing import Any


def estimate_text(text: str) -> float:
    """~3.8 characters per token for ASCII, ~1 token per wide character."""
    if not text:
        return 0.0
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    wide = len(text) - ascii_chars
    return ascii_chars / 3.8 + wide * 0.95


def estimate_json(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, str):
        return estimate_text(value)
    return estimate_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
