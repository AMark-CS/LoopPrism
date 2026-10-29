"""API prices for LLM models, used to turn token counts into USD.

Prices are USD per million tokens, copied from the providers' published API
price lists (see ``PRICING_SOURCES``) on ``PRICING_AS_OF``. They are list
prices for pay-as-you-go API use: subscription plans (Claude Pro/Max, ChatGPT)
are billed differently, so for those the result is "what this would cost on
the API".

Override or extend the table without touching code by putting
``~/.loopprism/pricing.json`` in place::

    {"claude-opus-5-5": {"input": 4, "output": 20, "cache_read": 0.2,
                         "cache_write": 5, "cache_write_1h": 8}}
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Optional

PRICING_AS_OF = "2026-10-28"
PRICING_SOURCES = {
    "anthropic": "https://platform.claude.com/docs/en/about-claude/pricing",
    "openai": "https://developers.openai.com/api/docs/pricing",
}


@dataclass(frozen=True)
class ModelPricing:
    """Pricing for a single model, in USD per million tokens.

    ``input_cost_per_m`` is the price of *uncached* input. Cache reads and
    writes default to the plain input price when not given.
    """

    input_cost_per_m: float
    output_cost_per_m: float
    cache_read_cost_per_m: Optional[float] = None
    cache_write_cost_per_m: Optional[float] = None  # 5-minute cache writes
    cache_write_1h_cost_per_m: Optional[float] = None
    # Some models charge more once the prompt is long (Haiku 5.5 over 100k).
    long_context: Optional["ModelPricing"] = None
    long_context_threshold: int = 100_000
    currency: str = "USD"

    def cost(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        cache_write_1h_tokens: int = 0,
    ) -> float:
        """Total USD cost. ``input_tokens`` excludes cached tokens."""
        per_m = 1_000_000
        read = self.cache_read_cost_per_m
        write = self.cache_write_cost_per_m
        write_1h = self.cache_write_1h_cost_per_m
        return (
            input_tokens * self.input_cost_per_m
            + output_tokens * self.output_cost_per_m
            + cache_read_tokens
            * (self.input_cost_per_m if read is None else read)
            + cache_write_tokens
            * (self.input_cost_per_m if write is None else write)
            + cache_write_1h_tokens
            * (self.input_cost_per_m if write_1h is None else write_1h)
        ) / per_m


def _claude(
    inp: float,
    out: float,
    write_5m: float,
    write_1h: float,
    read: float,
    **kw: Any,
) -> ModelPricing:
    return ModelPricing(inp, out, read, write_5m, write_1h, **kw)


_OPUS_45_TO_5 = _claude(5, 25, 6.25, 10, 0.5)
_OPUS_4 = _claude(15, 75, 18.75, 30, 1.5)
_SONNET_4 = _claude(3, 15, 3.75, 6, 0.3)
_FABLE_5 = _claude(10, 50, 12.5, 20, 1.0)
_FABLE_51 = _claude(10, 50, 12.5, 20, 0.25)

# Newest first: a loose name like "claude-opus" resolves to the newest match.
_ANTHROPIC: dict[str, ModelPricing] = {
    "claude-fable-5-1": _FABLE_51,
    "claude-mythos-5-1": _FABLE_51,
    "claude-fable-5": _FABLE_5,
    "claude-mythos-5": _FABLE_5,
    "claude-opus-5-5": _claude(4, 20, 5, 8, 0.2),
    "claude-opus-5": _OPUS_45_TO_5,
    "claude-opus-4-8": _OPUS_45_TO_5,
    "claude-opus-4-7": _OPUS_45_TO_5,
    "claude-opus-4-6": _OPUS_45_TO_5,
    "claude-opus-4-5": _OPUS_45_TO_5,
    "claude-opus-4-1": _OPUS_4,
    "claude-opus-4": _OPUS_4,
    "claude-sonnet-5-5": _claude(2, 10, 2.5, 4, 0.1),
    "claude-sonnet-5": _claude(2, 10, 2.5, 4, 0.2),
    "claude-sonnet-4-6": _SONNET_4,
    "claude-sonnet-4-5": _SONNET_4,
    "claude-sonnet-4": _SONNET_4,
    "claude-haiku-5-5": _claude(
        0.10, 0.50, 0.125, 0.20, 0.01,
        long_context=_claude(0.50, 2.50, 0.625, 1, 0.05),
    ),
    "claude-haiku-4-5": _claude(1, 5, 1.25, 2, 0.1),
    "claude-haiku-3-5": _claude(0.8, 4, 1, 1.6, 0.08),
    "claude-3-5-haiku": _claude(0.8, 4, 1, 1.6, 0.08),
}

_GPT_5_CODEX = ModelPricing(1.25, 10.0, cache_read_cost_per_m=0.125)

_OPENAI: dict[str, ModelPricing] = {
    "gpt-6-astra": ModelPricing(10.0, 50.0, 1.0),
    "gpt-6.1-sol": ModelPricing(2.0, 10.0, 0.10),
    "gpt-6.1-terra": ModelPricing(1.0, 5.0, 0.05),
    "gpt-6-luna": ModelPricing(0.10, 0.50, 0.01),
    # Promotional pricing, listed through 2026-11-21.
    "gpt-5.6-sol": ModelPricing(4.0, 20.0, 0.40),
    "gpt-5.6-cyber": ModelPricing(12.5, 75.0, 1.25),
    "gpt-5.3-codex": ModelPricing(1.75, 14.0, 0.175),
    # Older GPT-5 family (OpenAI model pages).
    "gpt-5.1-codex-max": _GPT_5_CODEX,
    "gpt-5.1-codex": _GPT_5_CODEX,
    "gpt-5-codex": _GPT_5_CODEX,
    "gpt-5": _GPT_5_CODEX,
}

# Other model families (USD per million tokens, the vendors' published pay-as-you-go API prices,
# first/standard tier where a price depends on prompt length). Exact ids first; a model that is
# not listed (a newer version, a regional variant) falls back to the newest known price of its
# family, see _FAMILIES. Override any of them in ~/.loopprism/pricing.json.
_OTHER: dict[str, ModelPricing] = {
    # DeepSeek
    "deepseek-chat": ModelPricing(0.28, 0.42, 0.028),
    "deepseek-reasoner": ModelPricing(0.28, 0.42, 0.028),
    "deepseek-v3.2": ModelPricing(0.28, 0.42, 0.028),
    "deepseek-v3.1": ModelPricing(0.56, 1.68, 0.07),
    "deepseek-r1": ModelPricing(0.55, 2.19, 0.14),
    # MiniMax
    "minimax-m2": ModelPricing(0.30, 1.20, 0.03, 0.375),
    "minimax-m2.1": ModelPricing(0.30, 1.20, 0.03, 0.375),
    # Zhipu / Z.ai GLM
    "glm-4.5": ModelPricing(0.60, 2.20, 0.11),
    "glm-4.5-air": ModelPricing(0.20, 1.10, 0.03),
    "glm-4.5-flash": ModelPricing(0.0, 0.0),
    "glm-4.6": ModelPricing(0.60, 2.20, 0.11),
    "glm-4.7": ModelPricing(0.60, 2.20, 0.11),
    "glm-5": ModelPricing(1.00, 3.20, 0.20),
    # Alibaba Qwen
    "qwen3-max": ModelPricing(1.20, 6.00),
    "qwen-max": ModelPricing(1.60, 6.40),
    "qwen-plus": ModelPricing(0.40, 1.20),
    "qwen-flash": ModelPricing(0.05, 0.40),
    "qwen3-coder-plus": ModelPricing(1.00, 5.00),
    "qwen3-coder-flash": ModelPricing(0.30, 1.50),
    # Moonshot Kimi
    "kimi-k2": ModelPricing(0.60, 2.50, 0.15),
    "kimi-k2-thinking": ModelPricing(0.60, 2.50, 0.15),
    # Google Gemini
    "gemini-2.5-pro": ModelPricing(1.25, 10.0, 0.125),
    "gemini-2.5-flash": ModelPricing(0.30, 2.50, 0.03),
    "gemini-2.5-flash-lite": ModelPricing(0.10, 0.40, 0.01),
    "gemini-3-pro": ModelPricing(2.00, 12.0, 0.20),
    "gemini-3-flash": ModelPricing(0.50, 3.00, 0.05),
}

_FREE = {"big-pickle"}

# (prefix of the normalised model id, price): the first match wins, so list the longer prefix first.
_FAMILIES: list[tuple[str, ModelPricing]] = [
    ("deepseek-r", _OTHER["deepseek-r1"]),
    ("deepseek", _OTHER["deepseek-v3.2"]),
    ("minimax", _OTHER["minimax-m2.1"]),
    ("glm-4.5-air", _OTHER["glm-4.5-air"]),
    ("glm-4", _OTHER["glm-4.7"]),
    ("glm-", _OTHER["glm-5"]),
    ("qwen3-coder-flash", _OTHER["qwen3-coder-flash"]),
    ("qwen3-coder", _OTHER["qwen3-coder-plus"]),
    ("qwen3-max", _OTHER["qwen3-max"]),
    ("qwen-flash", _OTHER["qwen-flash"]),
    ("qwen", _OTHER["qwen-plus"]),
    ("kimi", _OTHER["kimi-k2"]),
    ("gemini-3-flash", _OTHER["gemini-3-flash"]),
    ("gemini-3", _OTHER["gemini-3-pro"]),
    ("gemini-2.5-flash-lite", _OTHER["gemini-2.5-flash-lite"]),
    ("gemini-2.5-flash", _OTHER["gemini-2.5-flash"]),
    ("gemini", _OTHER["gemini-2.5-pro"]),
]

PROVIDER_PRICING: dict[str, dict[str, ModelPricing]] = {
    "anthropic": _ANTHROPIC,
    "openai": _OPENAI,
    # The tables below were not re-verified against the providers' price lists.
    "google": {
        "gemini-2.5-pro": ModelPricing(1.25, 5.0),
        "gemini-2.5-flash": ModelPricing(0.075, 0.3),
        "gemini-2.0-flash": ModelPricing(0.10, 0.40),
    },
    "deepseek": {
        "deepseek-chat": ModelPricing(0.27, 1.1),
        "deepseek-coder": ModelPricing(0.27, 1.1),
    },
    "ollama": {
        # Local models are free.
        "llama3": ModelPricing(0.0, 0.0),
        "llama3.1": ModelPricing(0.0, 0.0),
        "qwen2.5": ModelPricing(0.0, 0.0),
        "mixtral": ModelPricing(0.0, 0.0),
    },
}


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

_DATE_SUFFIX = re.compile(r"-(?:20\d{6}|latest)$")
_BEDROCK_SUFFIX = re.compile(r"-v\d+(?::\d+)?$")


def normalize_model(model: str) -> str:
    """Reduce the many spellings of a model id to the table's key.

    ``us.anthropic.claude-opus-4-5-20251101-v1:0``, ``claude-opus-4.5``,
    ``claude-opus-4-5[1m]`` all become ``claude-opus-4-5``.
    """
    m = model.strip().lower()
    m = re.sub(r"\[.*?\]$", "", m)  # claude-opus-4-5[1m]
    m = m.rsplit("/", 1)[-1]  # anthropic/claude-...
    if m.startswith(("us.", "eu.", "apac.", "global.")):
        m = m.split(".", 1)[1]
    m = m.removeprefix("anthropic.")
    m = _BEDROCK_SUFFIX.sub("", m)
    m = _DATE_SUFFIX.sub("", m)
    if m.startswith("claude-"):
        m = re.sub(r"(\d)\.(\d)", r"\1-\2", m)  # claude-opus-4.5
    return m


_overrides_cache: tuple[float, dict[str, ModelPricing]] = (-1.0, {})


def _override_path() -> Path:
    env = os.environ.get("LOOPPRISM_PRICING_FILE")
    return Path(env) if env else Path.home() / ".loopprism" / "pricing.json"


def _overrides() -> dict[str, ModelPricing]:
    """User price overrides from pricing.json (re-read when the file changes)."""
    global _overrides_cache
    path = _override_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        _overrides_cache = (-1.0, {})
        return {}
    if mtime == _overrides_cache[0]:
        return _overrides_cache[1]
    table: dict[str, ModelPricing] = {}
    try:
        for name, p in json.loads(path.read_text()).items():
            table[normalize_model(name)] = ModelPricing(
                float(p["input"]),
                float(p["output"]),
                _opt(p.get("cache_read")),
                _opt(p.get("cache_write")),
                _opt(p.get("cache_write_1h")),
            )
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        table = {}
    _overrides_cache = (mtime, table)
    return table


def _opt(value: Any) -> Optional[float]:
    return None if value is None else float(value)


def lookup(model: str) -> Optional[ModelPricing]:
    """Find a model's price in any provider table (or the user's overrides)."""
    if not model:
        return None
    key = normalize_model(model)
    over = _overrides()
    if key in over:
        return over[key]
    for table in (_ANTHROPIC, _OPENAI, _OTHER):
        if key in table:
            return table[key]
    if key.endswith("-free") or key in _FREE:
        return ModelPricing(0.0, 0.0)  # free tiers (OpenCode Zen's "-free" models, ...)
    for prefix, pricing in _FAMILIES:
        if key.startswith(prefix):
            return pricing
    return None


def get_pricing(provider: str, model: str) -> Optional[ModelPricing]:
    """Look up pricing for a provider + model combination.

    Falls back to partial matches (e.g. "claude-opus" resolves to the newest
    Opus in the table).
    """
    provider = provider.lower()
    key = normalize_model(model)

    over = _overrides()
    if key in over:
        return over[key]
    models = PROVIDER_PRICING.get(provider)
    if models is None:
        return None
    if key in models:
        return models[key]
    for name, pricing in models.items():
        if key in name or name in key:
            return pricing
    return None


def cost_from_tokens(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Compute USD cost from token counts.

    Returns 0.0 if pricing is unknown (local models, etc.).
    """
    pricing = get_pricing(provider, model)
    if pricing is None:
        return 0.0
    return pricing.cost(input_tokens, output_tokens)


def usage_cost(model: str, usage: dict[str, Any]) -> Optional[float]:
    """USD cost of one model's token usage, or None if the price is unknown.

    ``usage`` keys (all optional, token counts): ``input_tokens`` (uncached),
    ``output_tokens``, ``cache_read_tokens``, ``cache_write_tokens`` (5-minute),
    ``cache_write_1h_tokens``, and ``long_context`` (the prompt was over the
    model's long-context threshold).
    """
    pricing = lookup(model)
    if pricing is None:
        return None
    if usage.get("long_context") and pricing.long_context is not None:
        pricing = pricing.long_context
    return pricing.cost(
        int(usage.get("input_tokens") or 0),
        int(usage.get("output_tokens") or 0),
        int(usage.get("cache_read_tokens") or 0),
        int(usage.get("cache_write_tokens") or 0),
        int(usage.get("cache_write_1h_tokens") or 0),
    )


def usage_cost_parts(model: str, usage: dict[str, Any]) -> Optional[dict[str, float]]:
    """``usage_cost`` split into uncached input, cache reads, cache writes and output."""
    pricing = lookup(model)
    if pricing is None:
        return None
    if usage.get("long_context") and pricing.long_context is not None:
        pricing = pricing.long_context
    n = lambda k: int(usage.get(k) or 0)  # noqa: E731
    per_m = 1_000_000
    p_in = pricing.input_cost_per_m
    read = p_in if pricing.cache_read_cost_per_m is None else pricing.cache_read_cost_per_m
    write = p_in if pricing.cache_write_cost_per_m is None else pricing.cache_write_cost_per_m
    write_1h = p_in if pricing.cache_write_1h_cost_per_m is None else pricing.cache_write_1h_cost_per_m
    return {
        "input": n("input_tokens") * p_in / per_m,
        "cache_read": n("cache_read_tokens") * read / per_m,
        "cache_write": (n("cache_write_tokens") * write + n("cache_write_1h_tokens") * write_1h) / per_m,
        "output": n("output_tokens") * pricing.output_cost_per_m / per_m,
    }
