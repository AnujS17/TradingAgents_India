"""Guard for tradingagents.graph.debate_ledger's post-hoc ledger extractor.

DebateLedgerExtractor never touches the live bull/bear researcher prompts
-- it makes one additional structured-output call after their debate has
already concluded, reading the finished history text. These tests use a
fake LLM (no real provider call) to verify the wiring and, critically,
the never-raise contract.
"""

import pytest

from tradingagents.agents.schemas import DebateLedger, LedgerTopic
from tradingagents.graph.debate_ledger import DebateLedgerExtractor


class _FakeStructuredLLM:
    """Stands in for llm.with_structured_output(DebateLedger)."""

    def __init__(self, result=None, raise_on_invoke=False):
        self._result = result
        self._raise = raise_on_invoke
        self.last_prompt = None

    def invoke(self, prompt):
        self.last_prompt = prompt
        if self._raise:
            raise RuntimeError("provider exploded")
        return self._result


class _FakeLLM:
    """Stands in for the raw LLM passed to bind_structured."""

    def __init__(self, structured_llm):
        self._structured_llm = structured_llm

    def with_structured_output(self, schema):
        assert schema is DebateLedger
        return self._structured_llm


@pytest.mark.unit
def test_returns_the_structured_ledger_on_success():
    expected = DebateLedger(
        topics=[LedgerTopic(topic="Valuation", bull_point="Cheap on FCF.", bear_point="Expensive on P/E.")]
    )
    fake_structured = _FakeStructuredLLM(result=expected)
    extractor = DebateLedgerExtractor(_FakeLLM(fake_structured))

    ledger = extractor.extract("Bull Analyst: ...", "Bear Analyst: ...")

    assert ledger == expected
    assert "Bull Analyst" in fake_structured.last_prompt
    assert "Bear Analyst" in fake_structured.last_prompt


@pytest.mark.unit
def test_never_raises_when_structured_call_fails():
    fake_structured = _FakeStructuredLLM(raise_on_invoke=True)
    extractor = DebateLedgerExtractor(_FakeLLM(fake_structured))

    ledger = extractor.extract("bull text", "bear text")

    assert ledger == DebateLedger(topics=[])


@pytest.mark.unit
def test_never_raises_when_provider_does_not_support_structured_output():
    class _UnsupportedLLM:
        def with_structured_output(self, schema):
            raise NotImplementedError("this provider has no structured mode")

    extractor = DebateLedgerExtractor(_UnsupportedLLM())

    ledger = extractor.extract("bull text", "bear text")

    assert ledger == DebateLedger(topics=[])


@pytest.mark.unit
def test_returns_empty_ledger_when_structured_call_returns_wrong_type():
    # A malformed/unexpected provider response is not a DebateLedger instance.
    fake_structured = _FakeStructuredLLM(result={"not": "a DebateLedger"})
    extractor = DebateLedgerExtractor(_FakeLLM(fake_structured))

    ledger = extractor.extract("bull text", "bear text")

    assert ledger == DebateLedger(topics=[])
