"""Portfolio Manager: optional investment_horizon steering.

investment_horizon is state carried in from Propagator.create_initial_state
(threaded from the API's optional AnalysisRequest.time_horizon). The manager
must fold it into the prompt as a lens, not a mandate -- it should never
silently disappear when set, and must add nothing when absent.
"""

import pytest
from langchain_core.messages import AIMessage

from tradingagents.agents.managers.portfolio_manager import create_portfolio_manager


class CapturingLLM:
    """Forces invoke_structured_or_freetext's fallback path and records the prompt."""

    def __init__(self):
        self.captured_prompt = None

    def with_structured_output(self, schema):
        raise AttributeError("no structured output support in this fake")

    def invoke(self, prompt):
        self.captured_prompt = prompt
        return AIMessage(content="**Rating**: Hold")


def _state(investment_horizon: str = ""):
    return {
        "instrument_context": "The instrument to analyze is `SIEMENS.NS`.",
        "risk_debate_state": {
            "history": "aggressive: buy. conservative: hold.",
            "aggressive_history": "",
            "conservative_history": "",
            "neutral_history": "",
            "current_aggressive_response": "",
            "current_conservative_response": "",
            "current_neutral_response": "",
            "count": 2,
        },
        "investment_plan": "Research Manager recommends accumulating.",
        "trader_investment_plan": "**Action**: Buy",
        "investment_horizon": investment_horizon,
    }


@pytest.mark.unit
def test_prompt_includes_requested_horizon_as_a_lens_not_a_mandate():
    llm = CapturingLLM()

    create_portfolio_manager(llm)(_state(investment_horizon="3-6 months"))

    assert "3-6 months" in llm.captured_prompt
    assert "do not force a match" in llm.captured_prompt


@pytest.mark.unit
def test_prompt_omits_horizon_section_when_none_requested():
    llm = CapturingLLM()

    create_portfolio_manager(llm)(_state(investment_horizon=""))

    assert "Requested Holding Period" not in llm.captured_prompt


@pytest.mark.unit
def test_prompt_omits_horizon_section_when_key_missing_from_state():
    """Older/CLI callers may not seed investment_horizon at all -- must not KeyError."""
    llm = CapturingLLM()
    state = _state()
    del state["investment_horizon"]

    create_portfolio_manager(llm)(state)

    assert "Requested Holding Period" not in llm.captured_prompt
