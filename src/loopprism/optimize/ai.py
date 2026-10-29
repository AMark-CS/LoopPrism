"""Optional AI analysis: a model of the user's choice turns the findings into advice.

Only aggregate numbers are sent (spend by model and agent, cache hit rate, what each rule found,
and the saving it estimated). Never prompts, code, tool output, session titles, ids or paths.
The exact request is shown to the user first and sent only after they confirm.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

SYSTEM = (
    "You are a cost advisor for AI coding agents. You get aggregate usage numbers and the findings of a rule engine, "
    "each with an estimated saving. Write short, concrete advice in plain language: what to change first and why. "
    "Use only the numbers given, never invent figures, and say when an estimate is uncertain. "
    "You may add observations the rules missed, but label them as such. Answer in the user's language if it is stated, else English."
)


def build_messages(overview: dict[str, Any], result: dict[str, Any], language: str = "en") -> list[dict[str, str]]:
    t = overview["totals"]
    data = {
        "period_days": result.get("days"),
        "spend_usd": result["spend_usd"],
        "estimated_saving_usd": result["saving_usd"],
        "estimated_saving_pct": result["saving_pct"],
        "calls": t.get("steps"),
        "tokens": {"uncached_input": t.get("input"), "cache_read": t.get("cache_read"), "output": t.get("output")},
        "by_model": [{"model": m["key"], "spend_usd": m["cost"], "calls": m["steps"]} for m in overview["by_model"][:10]],
        "by_agent": [{"agent": a["key"], "spend_usd": a["cost"]} for a in overview["by_agent"]],
        "findings": [
            {"rule": s["id"], "estimated_saving_usd": s["saving_usd"], "sessions": s["sessions"], "confidence": s["confidence"],
             "examples": [e["detail"] for e in s["evidence"][:3]]}
            for s in result["suggestions"]
        ],
    }
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"Language: {language}\n\n" + json.dumps(data, ensure_ascii=False, indent=2)},
    ]


def endpoint(url: str) -> str:
    url = url.rstrip("/")
    return url if url.endswith("/chat/completions") else f"{url}/chat/completions"


def run(cfg: dict[str, Any], messages: list[dict[str, str]], timeout: float = 90.0) -> str:
    ai = cfg["ai"]
    r = httpx.post(
        endpoint(ai["url"]),
        headers={"Authorization": f"Bearer {ai['api_key']}", "Content-Type": "application/json"},
        json={"model": ai["model"], "messages": messages, "temperature": 0.2},
        timeout=timeout,
        follow_redirects=False,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"The model endpoint answered {r.status_code}: {r.text[:200]}")
    try:
        return str(r.json()["choices"][0]["message"]["content"]).strip()
    except (KeyError, IndexError, ValueError) as err:
        raise RuntimeError("The answer was not an OpenAI-style chat completion") from err
