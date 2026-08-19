"""Post-hoc extraction of a topic-by-topic bull/bear ledger.

DebateLedgerExtractor is NOT a LangGraph node and is never wired into
bull_researcher.py/bear_researcher.py's live debate loop -- it is a plain
helper, same shape as SignalProcessor (signal_processing.py) and
Reflector (reflection.py), invoked once by the caller (api/service.py)
after the debate has already concluded. This keeps the tuned, working
debate prompts completely untouched while still producing a real,
grounded (not fabricated) topic-paired view of what was actually argued.
"""

from __future__ import annotations

import logging
from typing import Any

from tradingagents.agents.schemas import DebateLedger
from tradingagents.agents.utils.structured import bind_structured

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = """You are reconciling a completed investment debate into a topic-by-topic ledger so a reader can compare both sides at a glance.

Below are the full bull and bear conversation histories from a multi-round debate about whether to invest in a stock. Read both sides and identify the distinct points of disagreement or discussion -- one row per topic (e.g. "valuation", "free cash flow", "RSI reading", "balance sheet").

For each topic, extract the bull side's point and the bear side's point in their own words, paraphrased concisely. Do not invent or exaggerate a claim neither side actually made. If only one side addressed a topic, leave the other side's field null -- do not fabricate a counterpoint for it. Produce one row per genuinely distinct topic; do not split one argument into several rows, and do not merge unrelated points into one row.

Bull conversation history:
{bull_history}

Bear conversation history:
{bear_history}
"""


class DebateLedgerExtractor:
    """Reads a finished bull/bear debate and pairs it into topic rows."""

    def __init__(self, quick_thinking_llm: Any):
        self.quick_thinking_llm = quick_thinking_llm

    def extract(self, bull_history: str, bear_history: str) -> DebateLedger:
        """Never raises. Any failure yields an empty ledger."""
        try:
            structured_llm = bind_structured(
                self.quick_thinking_llm, DebateLedger, "Debate Ledger Extractor"
            )
        except Exception as exc:  # noqa: BLE001 - never let extraction fail the run
            logger.warning("Debate Ledger Extractor: bind_structured failed (%s)", exc)
            return DebateLedger(topics=[])

        if structured_llm is None:
            return DebateLedger(topics=[])

        prompt = _PROMPT_TEMPLATE.format(
            bull_history=bull_history or "(no bull arguments recorded)",
            bear_history=bear_history or "(no bear arguments recorded)",
        )

        try:
            result = structured_llm.invoke(prompt)
        except Exception as exc:  # noqa: BLE001 - never let extraction fail the run
            logger.warning("Debate Ledger Extractor: structured call failed (%s)", exc)
            return DebateLedger(topics=[])

        if not isinstance(result, DebateLedger):
            logger.warning(
                "Debate Ledger Extractor: structured call returned %s, expected DebateLedger",
                type(result).__name__,
            )
            return DebateLedger(topics=[])

        return result
