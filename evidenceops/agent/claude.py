"""Claude API backend for the investigator and the log-only baseline.

Reads credentials the way the Anthropic SDK does (``ANTHROPIC_API_KEY``, or an
``ant auth login`` profile). Keys never go in files in this repository.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from evidenceops.agent.loop import ToolUse, Turn

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "high"
MAX_TOKENS = 16_000
KEY_HELP = (
    "No Anthropic credentials found. Create a key at https://console.anthropic.com/settings/keys "
    "and export it as ANTHROPIC_API_KEY."
)

# USD per million tokens: input, output, cache read, cache write (5 minute TTL).
PRICES = {
    "claude-opus-5-5": (4.00, 20.00, 0.20, 5.00),
    "claude-opus-5": (5.00, 25.00, 0.50, 6.25),
    "claude-opus-4-8": (5.00, 25.00, 0.50, 6.25),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20, 2.50),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
}


def usage_dict(usage: Any) -> Dict[str, int]:
    keys = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
    return {k: int(getattr(usage, k, 0) or 0) for k in keys}


def cost_of(model: str, usage: Dict[str, int]) -> float:
    price = PRICES.get(model)
    if price is None:
        return 0.0
    p_in, p_out, p_read, p_write = price
    return (
        usage.get("input_tokens", 0) * p_in
        + usage.get("output_tokens", 0) * p_out
        + usage.get("cache_read_input_tokens", 0) * p_read
        + usage.get("cache_creation_input_tokens", 0) * p_write
    ) / 1_000_000


def make_client() -> Any:
    try:
        import anthropic
    except ImportError as exc:
        raise SystemExit("pip install -r evidenceops/requirements.txt (the anthropic package is missing)") from exc
    return anthropic.Anthropic()


def request_options(model: str, effort: str) -> Dict[str, Any]:
    """Settings shared by every request: adaptive thinking, explicit effort,
    prompt caching, and server-side fallback when a safety classifier declines."""
    return dict(
        model=model,
        max_tokens=MAX_TOKENS,
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
        cache_control={"type": "ephemeral"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )


def create(client: Any, **kwargs: Any) -> Any:
    """One request, with credential errors turned into a readable exit."""
    import anthropic

    try:
        return client.beta.messages.create(**kwargs)
    except anthropic.AuthenticationError as exc:
        raise SystemExit(f"{KEY_HELP} ({exc.message})") from exc
    except TypeError as exc:
        if "authentication" in str(exc):
            raise SystemExit(KEY_HELP) from exc
        raise


class ClaudeModel:
    def __init__(self, model: str = DEFAULT_MODEL, effort: str = DEFAULT_EFFORT, client: Optional[Any] = None):
        self.name = model
        self.effort = effort
        self.client = client or make_client()

    def respond(self, system: str, tools: List[Dict[str, Any]], messages: List[Dict[str, Any]]) -> Turn:
        response = create(
            self.client,
            system=system,
            tools=tools,
            messages=messages,
            **request_options(self.name, self.effort),
        )
        usage = usage_dict(response.usage)
        served = getattr(response, "model", None) or self.name
        return Turn(
            content=response.content,
            tool_uses=[ToolUse(b.id, b.name, dict(b.input)) for b in response.content if b.type == "tool_use"],
            stop_reason=response.stop_reason or "",
            text="".join(b.text for b in response.content if b.type == "text"),
            usage=usage,
            cost_usd=cost_of(served, usage),
            model=served,
        )
