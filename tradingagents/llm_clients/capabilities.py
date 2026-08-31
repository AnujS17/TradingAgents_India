"""Declarative per-model capability table for OpenAI-compatible providers.

This is the single place that knows which model IDs reject which API
parameters or require which structured-output method. The LLM client
subclasses consult ``get_capabilities(model_name)`` instead of hardcoding
model-name ``if`` ladders, so adding a new model (or a new provider quirk)
means editing this table — not the client code.

Pattern adapted from the per-model ``compat:`` flags DeepSeek themselves
publish in their integration guides (e.g. the Oh My Pi config schema
documents ``supportsToolChoice``, ``requiresReasoningContentForToolCalls``
as declarative per-model fields).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


StructuredMethod = Literal[
    "function_calling",  # uses tools; respects supports_tool_choice
    "json_mode",         # uses response_format={"type":"json_object"}
    "json_schema",       # uses response_format={"type":"json_schema",...}
    "none",              # no structured output available; caller falls back to free-text
]


@dataclass(frozen=True)
class ModelCapabilities:
    """What an OpenAI-compatible model accepts at the API level."""

    supports_tool_choice: bool
    supports_json_mode: bool
    supports_json_schema: bool
    preferred_structured_method: StructuredMethod
    # DeepSeek thinking-mode models 400 if reasoning_content from prior
    # assistant turns is not echoed back on the next request.
    requires_reasoning_content_roundtrip: bool = False
    # MiniMax M2.x reasoning models need ``reasoning_split=True`` so the
    # <think> block lands in ``reasoning_details`` instead of polluting
    # ``content``. The flag is rejected by non-reasoning MiniMax models
    # (Coding Plan, MiniMax-Text-01, etc.), so we only set it where the
    # model actually consumes it. (#826)
    requires_reasoning_split: bool = False


# DeepSeek's thinking models accept the ``tools`` array but reject the
# ``tool_choice`` parameter (official Oh My Pi integration guide and the
# 400 response in issue #678). Their official tool-calling examples
# (api-docs.deepseek.com/guides/tool_calls) pass ``tools=[...]`` without
# ``tool_choice`` — we mirror that pattern by setting supports_tool_choice
# to False and letting the client suppress the kwarg.
_DEEPSEEK_THINKING = ModelCapabilities(
    supports_tool_choice=False,
    supports_json_mode=True,
    supports_json_schema=False,
    preferred_structured_method="function_calling",
    requires_reasoning_content_roundtrip=True,
)

_DEEPSEEK_CHAT = ModelCapabilities(
    supports_tool_choice=True,
    supports_json_mode=True,
    supports_json_schema=False,
    preferred_structured_method="function_calling",
)

# MiniMax M2.x reasoning models accept the tools array, but their
# tool_choice parameter is restricted to the enum {"none", "auto"}
# (platform.minimax.io/docs/api-reference/text-post). Langchain's
# function_calling path sends tool_choice as a function-spec dict, which
# MiniMax 400s — same shape as the DeepSeek bug. supports_tool_choice=False
# makes the dispatch in NormalizedChatOpenAI suppress the kwarg; the schema
# still ships as a tool. json_mode response_format is only for
# MiniMax-Text-01, not M2.x.
_MINIMAX_THINKING = ModelCapabilities(
    supports_tool_choice=False,
    supports_json_mode=False,
    supports_json_schema=False,
    preferred_structured_method="function_calling",
    requires_reasoning_split=True,
)

_DEFAULT = ModelCapabilities(
    supports_tool_choice=True,
    supports_json_mode=True,
    supports_json_schema=True,
    preferred_structured_method="function_calling",
)


# Exact-ID matches take precedence over pattern matches.
_BY_ID: dict[str, ModelCapabilities] = {
    "deepseek-chat": _DEEPSEEK_CHAT,
    "deepseek-reasoner": _DEEPSEEK_THINKING,
    "deepseek-v4-flash": _DEEPSEEK_THINKING,
    "deepseek-v4-pro": _DEEPSEEK_THINKING,
    # MiniMax — full official model lineup per
    # platform.minimax.io/docs/api-reference/text-openai-api
    "MiniMax-M2.7": _MINIMAX_THINKING,
    "MiniMax-M2.7-highspeed": _MINIMAX_THINKING,
    "MiniMax-M2.5": _MINIMAX_THINKING,
    "MiniMax-M2.5-highspeed": _MINIMAX_THINKING,
    "MiniMax-M2.1": _MINIMAX_THINKING,
    "MiniMax-M2.1-highspeed": _MINIMAX_THINKING,
    "MiniMax-M2": _MINIMAX_THINKING,
}

# Forward-compat patterns. New ``deepseek-v5-*`` / ``deepseek-reasoner-*``
# or ``MiniMax-M3*`` variants inherit the thinking-mode quirks automatically.
_BY_PATTERN: list[tuple[re.Pattern[str], ModelCapabilities]] = [
    (re.compile(r"^deepseek-v\d"), _DEEPSEEK_THINKING),
    (re.compile(r"^deepseek-reasoner"), _DEEPSEEK_THINKING),
    (re.compile(r"^MiniMax-M\d"), _MINIMAX_THINKING),
]


def _strip_vendor_prefix(model_name: str) -> str:
    """Drop an aggregator's ``vendor/`` prefix and any ``:variant`` suffix.

    OpenRouter addresses the same model as ``deepseek/deepseek-v4-flash-0731``
    where its own provider calls it ``deepseek-v4-flash``. Every key and
    pattern in the tables above is written in the bare, provider-native
    form, so a slug went through untouched, matched nothing, and silently
    fell through to _DEFAULT -- which claims supports_tool_choice=True and
    requires_reasoning_content_roundtrip=False, the exact opposite of what
    a DeepSeek thinking model needs. The quirks this whole module exists to
    encode were therefore never applied to any OpenRouter-routed DeepSeek
    run (2026-08-26 to 2026-08-31).

    Also strips a trailing variant (``:free``, ``:nitro``, ``:exacto``,
    ``:floor``), which is a routing instruction to the aggregator rather
    than part of the model's identity.

    A bare name with neither is returned unchanged, so provider-native
    callers are unaffected.
    """
    without_variant = model_name.split(":", 1)[0]
    return without_variant.rsplit("/", 1)[-1]


def get_capabilities(model_name: str) -> ModelCapabilities:
    """Resolve capabilities by exact ID, then pattern, then default.

    Tried on the name as given first so a provider-native id always wins,
    then on the vendor-stripped form so an aggregator slug resolves to the
    same entry.
    """
    for candidate in (model_name, _strip_vendor_prefix(model_name)):
        if candidate in _BY_ID:
            return _BY_ID[candidate]
        for pattern, caps in _BY_PATTERN:
            if pattern.match(candidate):
                return caps
    return _DEFAULT
