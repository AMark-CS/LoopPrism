"""Pricing models for major LLM providers.

This module defines current pricing for supported models, used by the
cost attribution engine to compute USD costs from token counts.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ModelPricing:
    """Pricing for a single model, in USD per million tokens."""

    input_cost_per_m: float
    output_cost_per_m: float
    currency: str = "USD"

    def cost(
        self,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Compute total cost in USD.

        Args:
            input_tokens: Number of input tokens.
            output_tokens: Number of output tokens.

        Returns:
            Total cost in USD.
        """
        return (
            (input_tokens / 1_000_000) * self.input_cost_per_m
            + (output_tokens / 1_000_000) * self.output_cost_per_m
        )


# --- Provider pricing tables ---
# Prices are approximate as of mid-2026. Update as needed.

PROVIDER_PRICING: dict[str, dict[str, ModelPricing]] = {
    "anthropic": {
        "claude-opus-4-8": ModelPricing(input_cost_per_m=15.0, output_cost_per_m=75.0),
        "claude-sonnet-4-7": ModelPricing(input_cost_per_m=3.0, output_cost_per_m=15.0),
        "claude-haiku-4-5": ModelPricing(input_cost_per_m=0.8, output_cost_per_m=4.0),
        # Legacy
        "claude-3-opus": ModelPricing(input_cost_per_m=15.0, output_cost_per_m=75.0),
        "claude-3-sonnet": ModelPricing(input_cost_per_m=3.0, output_cost_per_m=15.0),
        "claude-3-haiku": ModelPricing(input_cost_per_m=0.25, output_cost_per_m=1.25),
    },
    "openai": {
        "gpt-4o": ModelPricing(input_cost_per_m=2.5, output_cost_per_m=10.0),
        "gpt-4o-mini": ModelPricing(input_cost_per_m=0.15, output_cost_per_m=0.6),
        "gpt-4-turbo": ModelPricing(input_cost_per_m=10.0, output_cost_per_m=30.0),
        "gpt-4": ModelPricing(input_cost_per_m=30.0, output_cost_per_m=60.0),
        "gpt-3.5-turbo": ModelPricing(input_cost_per_m=0.5, output_cost_per_m=1.5),
    },
    "google": {
        "gemini-2.5-pro": ModelPricing(input_cost_per_m=1.25, output_cost_per_m=5.0),
        "gemini-2.5-flash": ModelPricing(input_cost_per_m=0.075, output_cost_per_m=0.3),
        "gemini-2.0-flash": ModelPricing(input_cost_per_m=0.10, output_cost_per_m=0.40),
    },
    "deepseek": {
        "deepseek-chat": ModelPricing(input_cost_per_m=0.27, output_cost_per_m=1.1),
        "deepseek-coder": ModelPricing(input_cost_per_m=0.27, output_cost_per_m=1.1),
    },
    "ollama": {
        # Local models — typically free, priced at $0
        "llama3": ModelPricing(input_cost_per_m=0.0, output_cost_per_m=0.0),
        "llama3.1": ModelPricing(input_cost_per_m=0.0, output_cost_per_m=0.0),
        "qwen2.5": ModelPricing(input_cost_per_m=0.0, output_cost_per_m=0.0),
        "mixtral": ModelPricing(input_cost_per_m=0.0, output_cost_per_m=0.0),
    },
}


def get_pricing(
    provider: str,
    model: str,
) -> Optional[ModelPricing]:
    """Look up pricing for a provider + model combination.

    Falls back to partial matches (e.g. "claude" → "claude-opus-4-8").

    Args:
        provider: Provider name (e.g. "anthropic", "openai").
        model: Model name (e.g. "claude-opus-4-8").

    Returns:
        ModelPricing if found, None otherwise.
    """
    provider = provider.lower()
    model = model.lower()

    if provider in PROVIDER_PRICING:
        models = PROVIDER_PRICING[provider]
        # Exact match
        if model in models:
            return models[model]
        # Partial match (e.g. "claude-opus" → "claude-opus-4-8")
        for name, pricing in models.items():
            if model in name or name in model:
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