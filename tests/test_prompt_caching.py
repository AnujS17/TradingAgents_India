"""invoke_with_cache_breakpoint tests.

The debate/risk nodes (bull/bear researcher, aggressive/neutral/conservative
debator) each run multiple rounds per graph invocation and resend the same
instrument/market/sentiment/news/fundamentals reports every round. For
Anthropic this function routes the unchanging prefix through an explicit
cache breakpoint; every other provider (this repo's default is DeepSeek)
must see byte-identical behavior to a single concatenated prompt string.
"""

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

from tradingagents.agents.utils.prompt_caching import invoke_with_cache_breakpoint


class FakeNonAnthropicLLM:
    """Stands in for the default DeepSeek client — deliberately NOT a ChatAnthropic subclass."""

    def __init__(self):
        self.received = None

    def invoke(self, prompt):
        self.received = prompt
        return "ok"


@pytest.mark.unit
def test_non_anthropic_llm_receives_plain_concatenated_string():
    llm = FakeNonAnthropicLLM()

    invoke_with_cache_breakpoint(llm, "STATIC ", "DYNAMIC")

    assert llm.received == "STATIC DYNAMIC"
    assert isinstance(llm.received, str)


@pytest.mark.unit
def test_non_anthropic_concatenation_order_is_static_then_dynamic():
    llm = FakeNonAnthropicLLM()

    invoke_with_cache_breakpoint(llm, "role framing + reports\n", "history + last argument")

    assert llm.received == "role framing + reports\nhistory + last argument"


@pytest.mark.unit
def test_anthropic_llm_receives_cache_control_breakpoint(monkeypatch):
    # Use a real ChatAnthropic instance (no network call — invoke is patched
    # at the class level) so isinstance(llm, ChatAnthropic) genuinely passes;
    # a MagicMock would not trigger the Anthropic branch at all, silently
    # testing nothing. ChatAnthropic is a pydantic model, so instance-level
    # attribute assignment (llm.invoke = ...) is rejected by pydantic's
    # __setattr__ validation — patching the class method sidesteps that.
    captured = {}

    def fake_invoke(self, messages, *args, **kwargs):
        captured["messages"] = messages
        return "ok"

    monkeypatch.setattr(ChatAnthropic, "invoke", fake_invoke)
    llm = ChatAnthropic(model="claude-3-5-haiku-latest", api_key="test-key")

    invoke_with_cache_breakpoint(llm, "STATIC BLOCK", "DYNAMIC BLOCK")

    called_messages = captured["messages"]
    assert len(called_messages) == 1
    message = called_messages[0]
    assert isinstance(message, HumanMessage)

    blocks = message.content
    assert blocks[0] == {
        "type": "text",
        "text": "STATIC BLOCK",
        "cache_control": {"type": "ephemeral"},
    }
    assert blocks[1] == {"type": "text", "text": "DYNAMIC BLOCK"}


@pytest.mark.unit
def test_anthropic_only_the_static_block_carries_cache_control(monkeypatch):
    captured = {}

    def fake_invoke(self, messages, *args, **kwargs):
        captured["messages"] = messages
        return "ok"

    monkeypatch.setattr(ChatAnthropic, "invoke", fake_invoke)
    llm = ChatAnthropic(model="claude-3-5-haiku-latest", api_key="test-key")

    invoke_with_cache_breakpoint(llm, "STATIC", "DYNAMIC")

    blocks = captured["messages"][0].content
    assert "cache_control" in blocks[0]
    assert "cache_control" not in blocks[1]


@pytest.mark.unit
def test_return_value_passes_through_unchanged():
    llm = FakeNonAnthropicLLM()

    result = invoke_with_cache_breakpoint(llm, "a", "b")

    assert result == "ok"
