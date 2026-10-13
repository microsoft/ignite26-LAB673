"""List prices in USD used for plan cost estimates. Planning figures only.

Azure OpenAI Global Standard pay-as-you-go and Azure AI Search list prices, rounded.
Regional, Data Zone, provisioned and negotiated prices differ; unknown models and tiers
return None so callers say the cost is unknown rather than guess.
"""
from __future__ import annotations

# model -> (input, output) USD per 1M tokens
MODEL_USD_PER_MILLION = {
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5-nano": (0.05, 0.40),
    "gpt-5": (1.25, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "text-embedding-3-small": (0.02, 0.0),
    "text-embedding-3-large": (0.13, 0.0),
    "text-embedding-ada-002": (0.10, 0.0),
}
# Search SKU -> USD per day for one search unit
SEARCH_USD_PER_DAY = {"free": 0.0, "basic": 2.42, "standard": 8.05, "standard2": 32.24,
                      "standard3": 64.48}
PRICE_BASIS = ("Azure list prices (Global Standard pay-as-you-go for models); "
               "your agreement may differ.")


def model_prices(model: str | None) -> tuple[float, float] | None:
    return MODEL_USD_PER_MILLION.get((model or "").casefold())


def token_cost_usd(model: str | None, prompt_tokens: float,
                   completion_tokens: float = 0.0) -> float | None:
    prices = model_prices(model)
    if prices is None:
        return None
    return (prompt_tokens * prices[0] + completion_tokens * prices[1]) / 1_000_000


def token_cost_range_usd(model: str | None, total_tokens: float) -> tuple[float, float] | None:
    """Total tokens with an unknown prompt/completion split: all input to all output."""
    prices = model_prices(model)
    if prices is None:
        return None
    return (total_tokens * min(prices) / 1_000_000, total_tokens * max(prices) / 1_000_000)


def search_usd_per_day(sku: str | None, units: int = 1) -> float | None:
    rate = SEARCH_USD_PER_DAY.get((sku or "").casefold())
    return None if rate is None else rate * units


def dollars(value: float | None) -> str:
    """Plain dollars at a precision that never rounds a real cost down to $0."""
    if value is None:
        return "unknown"
    if value == 0:
        return "$0"
    if value < 0.01:
        return "$0.01"
    return f"${value:,.2f}" if value < 100 else f"${value:,.0f}"


def dollar_range(low: float | None, high: float | None) -> str:
    if low is None or high is None:
        return "unknown"
    first, second = dollars(low), dollars(high)
    return first if first == second else f"{first}–{second}"
