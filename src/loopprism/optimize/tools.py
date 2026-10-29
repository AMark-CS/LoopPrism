"""Tools that save tokens or money, matched to the suggestions.

A short reviewed catalog (checked by hand) is refreshed from GitHub (stars, last push, licence,
description) at most once a day, and a few extra repositories are discovered by search for each
kind of suggestion and marked "not reviewed". Only permissively licensed, recently updated,
not-archived projects are listed. Nothing is installed: each entry links to its GitHub page.
Turn the lookup off in the Optimize settings and only the cached data is shown.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

PERMISSIVE = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "MPL-2.0", "Unlicense", "0BSD", "CC0-1.0"}
MAX_AGE_DAYS = 180
MIN_STARS_DISCOVERED = 300
CACHE_SECONDS = 24 * 3600

# kind: what the tool does for the user; tags match the suggestions in rules.COPY.
CATALOG: list[dict[str, Any]] = [
    {"repo": "rtk-ai/rtk", "kind": "compress", "tags": ["big_tool_output", "repeated_calls"],
     "why": "A CLI proxy that shortens the output of common dev commands before the model reads it."},
    {"repo": "headroomlabs-ai/headroom", "kind": "compress", "tags": ["big_tool_output", "long_session"],
     "why": "Compresses tool outputs, logs, files and RAG chunks before they reach the model."},
    {"repo": "zilliztech/claude-context", "kind": "retrieval", "tags": ["big_tool_output", "long_session"],
     "why": "Code search over MCP: the agent fetches the relevant code instead of reading whole files."},
    {"repo": "ooples/token-optimizer-mcp", "kind": "measure", "tags": ["low_cache_hit", "big_tool_output"],
     "why": "Measures token savings per agent and trims context."},
    {"repo": "microsoft/LLMLingua", "kind": "compress", "tags": ["long_session", "big_tool_output"],
     "why": "Prompt compression research and library: shorter prompts with little loss."},
    {"repo": "musistudio/claude-code-router", "kind": "router", "tags": ["cheaper_model"],
     "why": "Routes requests across models, so simple tasks can go to a cheaper one."},
    {"repo": "Portkey-AI/gateway", "kind": "gateway", "tags": ["cheaper_model", "low_cache_hit"],
     "why": "An AI gateway with routing, fallbacks and caching across many providers."},
]

# Search queries per suggestion, for projects that are not in the catalog yet.
DISCOVERY = {
    "big_tool_output": ["token reduce topic:claude-code", "context compression topic:mcp"],
    "low_cache_hit": ["prompt cache topic:claude-code", "llm cache proxy topic:ai-agent"],
    "cheaper_model": ["model router topic:claude-code", "llm gateway cost topic:ai-agent"],
    "long_session": ["context management topic:claude-code", "session summary topic:ai-agent"],
    "repeated_calls": ["token savings topic:claude-code"],
}
EXCLUDE_WORDS = ("awesome", "tutorial", "course", "dotfiles")


def _cache_path() -> Path:
    env = os.environ.get("LOOPPRISM_TOOLS_CACHE")
    return Path(env) if env else Path.home() / ".loopprism" / "tools-cache.json"


def _headers() -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "User-Agent": "LoopPrism"}
    if os.environ.get("GITHUB_TOKEN"):
        h["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    return h


def _days_ago(iso: Optional[str]) -> Optional[int]:
    if not iso:
        return None
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(iso.replace("Z", "+00:00"))).days
    except ValueError:
        return None


def _entry(repo: dict[str, Any], **extra: Any) -> dict[str, Any]:
    lic = (repo.get("license") or {}).get("spdx_id")
    return {
        "repo": repo["full_name"], "url": repo["html_url"], "stars": repo.get("stargazers_count"), "license": lic,
        "pushed_days_ago": _days_ago(repo.get("pushed_at")), "description": repo.get("description") or "",
        "archived": bool(repo.get("archived")), **extra,
    }


def acceptable(e: dict[str, Any]) -> bool:
    return (e["license"] in PERMISSIVE and not e["archived"]
            and e["pushed_days_ago"] is not None and e["pushed_days_ago"] <= MAX_AGE_DAYS)


def fetch(client: Optional[httpx.Client] = None) -> list[dict[str, Any]]:
    """Live data for the catalog plus discovered projects. Network errors on one repo skip that repo."""
    own = client is None
    client = client or httpx.Client(timeout=10, headers=_headers())
    out: list[dict[str, Any]] = []
    seen = {c["repo"].lower() for c in CATALOG}
    try:
        for c in CATALOG:
            try:
                r = client.get(f"https://api.github.com/repos/{c['repo']}")
                if r.status_code != 200:
                    continue
                e = _entry(r.json(), tags=c["tags"], kind=c["kind"], why=c["why"], reviewed=True)
                if acceptable(e):
                    out.append(e)
            except httpx.HTTPError:
                continue
        for rule, queries in DISCOVERY.items():
            found = 0
            for q in queries:
                try:
                    r = client.get("https://api.github.com/search/repositories",
                                   params={"q": f"{q} stars:>={MIN_STARS_DISCOVERED}", "sort": "stars", "per_page": 10})
                    if r.status_code != 200:
                        break
                    for item in r.json().get("items", []):
                        name = item["full_name"].lower()
                        if name in seen or any(w in name for w in EXCLUDE_WORDS):
                            continue
                        e = _entry(item, tags=[rule], kind="discovered", why=item.get("description") or "", reviewed=False)
                        if acceptable(e):
                            seen.add(name)
                            out.append(e)
                            found += 1
                        if found >= 2:
                            break
                except httpx.HTTPError:
                    break
                if found >= 2:
                    break
    finally:
        if own:
            client.close()
    return out


def tools_for(live: bool, force: bool = False, fetcher=fetch) -> dict[str, Any]:
    """The tool list, from the day's cache or live. ``source`` says which."""
    p = _cache_path()
    cached: Optional[dict[str, Any]] = None
    try:
        cached = json.loads(p.read_text())
    except (OSError, ValueError):
        pass
    fresh = cached and time.time() - cached.get("at", 0) < CACHE_SECONDS
    if cached and fresh and not force:
        return {"tools": cached["tools"], "fetched_at": cached["at"], "source": "cache"}
    if not live:
        return {"tools": cached["tools"] if cached else [], "fetched_at": cached.get("at") if cached else None,
                "source": "cache" if cached else "off"}
    try:
        tools = fetcher()
    except Exception:  # offline: show what we had
        tools = []
    if tools:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"at": time.time(), "tools": tools}))
        return {"tools": tools, "fetched_at": time.time(), "source": "live"}
    return {"tools": cached["tools"] if cached else _offline(), "fetched_at": cached.get("at") if cached else None,
            "source": "cache" if cached else "offline"}


def _offline() -> list[dict[str, Any]]:
    """The reviewed catalog without live numbers, so the page is useful offline."""
    return [{"repo": c["repo"], "url": f"https://github.com/{c['repo']}", "stars": None, "license": None, "pushed_days_ago": None,
             "description": c["why"], "archived": False, "tags": c["tags"], "kind": c["kind"], "why": c["why"], "reviewed": True}
            for c in CATALOG]
