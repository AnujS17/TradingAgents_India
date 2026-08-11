"""Anthropic prompt-cache breakpoint helper for the debate/risk nodes.

Bull/bear researcher and the three risk debators each run multiple rounds per
graph invocation, and re-send the same instrument/market/sentiment/news/
fundamentals reports (and, for risk debators, the same trader decision) on
every round — only the debate history and the opponents' latest arguments
actually change round to round. For Anthropic models this is exactly what
prompt caching is for: split the prompt into a static prefix (identical
across rounds) and a dynamic suffix (changes every round), and Anthropic
caches the static prefix server-side so repeat rounds only pay full price for
the suffix.

Every other provider (this repo's default is DeepSeek) gets byte-identical
behavior to the pre-split prompt — plain concatenation, one string, no
special handling. Some of them (DeepSeek included) cache a repeated prefix
automatically server-side as long as the static content comes first, which it
already does here, so callers may still see a latency/cost benefit even off
the explicit-breakpoint path — just not one this code controls or verifies.

Caveat: Anthropic's minimum cacheable block size is model-dependent (roughly
1024 tokens for Sonnet-class, 2048 for Haiku-class, as of the API version this
was written against). A static_context shorter than that is not an error —
the breakpoint is simply a no-op and normal per-call pricing applies — but it
means a thin static block (e.g. an early debate round with sparse reports)
may not actually get cached even though the breakpoint is set.
"""

from __future__ import annotations

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage


def invoke_with_cache_breakpoint(llm, static_context: str, dynamic_context: str):
    """Invoke ``llm`` with ``static_context`` cached and ``dynamic_context`` fresh.

    ``static_context + dynamic_context`` (that exact order, that exact
    concatenation) must equal what the caller would otherwise have passed to
    ``llm.invoke(...)`` as a single string — this function changes how a
    prompt is delivered to Anthropic, not what it says.
    """
    if isinstance(llm, ChatAnthropic):
        message = HumanMessage(
            content=[
                {
                    "type": "text",
                    "text": static_context,
                    "cache_control": {"type": "ephemeral"},
                },
                {"type": "text", "text": dynamic_context},
            ]
        )
        return llm.invoke([message])
    return llm.invoke(static_context + dynamic_context)
