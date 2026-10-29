"""Optimize settings: ``~/.loopprism/optimize.json`` (live tool lookup, optional AI analysis)."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DEFAULTS: dict[str, Any] = {"live_tools": True, "ai": {"enabled": False, "url": "", "api_key": "", "model": ""}}


def path() -> Path:
    env = os.environ.get("LOOPPRISM_OPTIMIZE_FILE")
    return Path(env) if env else Path.home() / ".loopprism" / "optimize.json"


def load() -> dict[str, Any]:
    cfg = json.loads(json.dumps(DEFAULTS))
    try:
        data = json.loads(path().read_text())
    except (OSError, ValueError):
        return cfg
    if isinstance(data, dict):
        cfg["live_tools"] = bool(data.get("live_tools", True))
        ai = data.get("ai") if isinstance(data.get("ai"), dict) else {}
        for k in ("url", "api_key", "model"):
            cfg["ai"][k] = str(ai.get(k) or "")
        cfg["ai"]["enabled"] = bool(ai.get("enabled"))
    return cfg


def valid_url(url: str) -> bool:
    """https anywhere, plain http only to this machine (a local model)."""
    try:
        u = urlparse(url)
    except ValueError:
        return False
    if not u.hostname:
        return False
    return u.scheme == "https" or (u.scheme == "http" and u.hostname in ("localhost", "127.0.0.1", "::1"))


def save(patch: dict[str, Any]) -> dict[str, Any]:
    """Apply a partial update; an empty ``api_key`` keeps the stored one (the UI never receives it)."""
    cfg = load()
    if "live_tools" in patch:
        cfg["live_tools"] = bool(patch["live_tools"])
    ai = patch.get("ai")
    if isinstance(ai, dict):
        if "url" in ai:
            url = str(ai["url"]).strip()
            if url and not valid_url(url):
                raise ValueError("The URL must be https:// (or http:// for a model on this computer).")
            cfg["ai"]["url"] = url
        if "model" in ai:
            cfg["ai"]["model"] = re.sub(r"\s+", "", str(ai["model"]))[:120]
        if ai.get("api_key"):
            cfg["ai"]["api_key"] = str(ai["api_key"]).strip()
        if ai.get("clear_key"):
            cfg["ai"]["api_key"] = ""
        if "enabled" in ai:
            cfg["ai"]["enabled"] = bool(ai["enabled"])
    if cfg["ai"]["enabled"] and not (cfg["ai"]["url"] and cfg["ai"]["model"] and cfg["ai"]["api_key"]):
        raise ValueError("Fill in the URL, the model and the API key before turning AI analysis on.")
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # the key is a secret: owner only
    with os.fdopen(fd, "w") as fh:
        json.dump(cfg, fh, indent=2)
    os.replace(tmp, p)
    return cfg


def public(cfg: dict[str, Any]) -> dict[str, Any]:
    """What the UI may see: never the key itself."""
    ai = cfg["ai"]
    return {"live_tools": cfg["live_tools"], "ai": {"enabled": ai["enabled"], "url": ai["url"], "model": ai["model"], "key_set": bool(ai["api_key"])}}
