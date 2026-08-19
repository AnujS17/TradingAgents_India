"""The seam between the HTTP layer and the analysis engine.

**This is the only module in ``api/`` that imports ``tradingagents``.**
Routers, workers and persistence call in here; nothing else reaches past it.
That keeps the engine replaceable and makes a future repo split a one-file
change rather than an import untangling.

The engine is synchronous and takes ~220s (fast) to ~800s (detailed), so
``run_analysis`` is only ever called from a worker process — never from a
request handler.
"""

from __future__ import annotations

from datetime import date as Date

from api.schemas import AnalysisProfile, DebateLedger, LedgerTopic, Reports, TradeLevels, Verdict


def build_config(profile: AnalysisProfile) -> dict:
    """Engine config for a profile.

    Imported lazily: ``tradingagents`` pulls in langchain and the whole vendor
    stack, which is several seconds of import time. A web process that only
    serves /health should not pay that.
    """
    from tradingagents.default_config import DEFAULT_CONFIG, get_fast_config

    if profile is AnalysisProfile.FAST:
        return get_fast_config()
    return DEFAULT_CONFIG.copy()


def config_fingerprint(config: dict) -> str:
    """Stable hash of the settings that change an analysis's *content*.

    Two runs sharing a fingerprint are interchangeable, so one can serve the
    other from cache. Keys that affect only scheduling or presentation are
    excluded — ``analyst_concurrency_limit`` changes how fast a run goes, not
    what it concludes, so a fast and a sequential run of the same profile
    should not be treated as different products.
    """
    import hashlib
    import json

    relevant = {
        key: config.get(key)
        for key in (
            "llm_provider",
            "deep_think_llm",
            "quick_think_llm",
            "max_debate_rounds",
            "max_risk_discuss_rounds",
            "report_style",
            "max_output_tokens",
            "llm_temperature",
            "llm_seed",
            "company_news_lookback_days",
            "data_vendors",
            "tool_vendors",
        )
    }
    payload = json.dumps(relevant, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _field(rendered: str, label: str) -> str | None:
    """Read one ``**Label**: value`` line out of a rendered agent report."""
    import re

    match = re.search(rf"^\*\*{re.escape(label)}\*\*:\s*(.+)$", rendered, re.MULTILINE)
    if match is None:
        return None
    value = match.group(1).strip()
    return value or None


def _float_field(rendered: str, label: str) -> float | None:
    raw = _field(rendered, label)
    if raw is None:
        return None
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def _extract_verdict(state: dict) -> Verdict:
    """Recover the structured decision from the rendered agent reports.

    PROVISIONAL, and worth understanding before relying on it. The graph does
    not keep the parsed pydantic objects: ``invoke_structured_or_freetext``
    renders ``TraderProposal``/``PortfolioDecision`` to markdown and returns
    only the string, so ``trader_investment_plan`` and ``final_trade_decision``
    are all that reach state. Rather than reverse-engineering prose blindly,
    this parses the exact ``**Label**: value`` lines that ``render_trader_
    proposal`` and ``render_pm_decision`` emit, and
    ``tests/test_api_verdict_parsing.py`` round-trips real schema instances
    through renderer -> parser. If anyone changes a renderer, that test fails
    immediately instead of this silently returning empty verdicts.

    The better fix is to thread the parsed objects into state and delete this;
    it needs a change to the shared helper used by four agents, so it is
    deliberately not bundled into the API scaffold.

    A missing stop-loss is EXPECTED, not an error — the trader schema drops a
    stop it cannot make coherent rather than emitting one offering no
    protection.
    """
    trader = state.get("trader_investment_plan") or ""
    final = state.get("final_trade_decision") or ""

    return Verdict(
        rating=_field(final, "Rating"),
        price_target=_float_field(final, "Price Target"),
        time_horizon=_field(final, "Time Horizon"),
        levels=TradeLevels(
            action=_field(trader, "Action"),
            entry_price=_float_field(trader, "Entry Price"),
            stop_loss=_float_field(trader, "Stop Loss"),
            position_sizing=_field(trader, "Position Sizing"),
        ),
    )


def _extract_reports(state: dict) -> Reports:
    debate = state.get("investment_debate_state") or {}
    risk = state.get("risk_debate_state") or {}
    return Reports(
        market=state.get("market_report") or None,
        sentiment=state.get("sentiment_report") or None,
        news=state.get("news_report") or None,
        fundamentals=state.get("fundamentals_report") or None,
        bull_case=debate.get("bull_history") or None,
        bear_case=debate.get("bear_history") or None,
        investment_plan=debate.get("judge_decision") or None,
        trader_plan=state.get("trader_investment_plan") or None,
        risk_debate=risk.get("history") or None,
        final_decision=state.get("final_trade_decision") or None,
    )


def run_analysis(
    ticker: str,
    analysis_date: Date,
    profile: AnalysisProfile,
    refresh_data: bool = False,
) -> tuple[Verdict, Reports, DebateLedger]:
    """Execute one full analysis. Blocking, minutes long, worker-only.

    Note the engine freezes its own inputs per (ticker, date) via
    ``dataflows.snapshot_cache``, so a second run of the same ticker and date
    re-uses the first run's news, filings and market snapshot and only repeats
    the LLM reasoning. That is a separate layer from the run cache above it,
    which skips the reasoning too.
    """
    from tradingagents.graph.debate_ledger import DebateLedgerExtractor
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    config = build_config(profile)
    # refresh_data=True busts the day's snapshot so news/filings/social are
    # re-fetched. Left False, a repeat run re-reasons over IDENTICAL inputs,
    # which is what makes two runs comparable — any difference is the model,
    # not the data.
    config["snapshot_cache_enabled"] = not refresh_data

    graph = TradingAgentsGraph(config=config)
    final_state, _signal = graph.propagate(ticker, str(analysis_date))

    debate_state = final_state.get("investment_debate_state") or {}
    agent_ledger = DebateLedgerExtractor(graph.quick_thinking_llm).extract(
        debate_state.get("bull_history", ""), debate_state.get("bear_history", "")
    )
    ledger = DebateLedger(
        topics=[
            LedgerTopic(topic=t.topic, bull_point=t.bull_point, bear_point=t.bear_point)
            for t in agent_ledger.topics
        ]
    )

    return _extract_verdict(final_state), _extract_reports(final_state), ledger
