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

from api.schemas import AnalysisProfile, Reports, TradeLevels, Verdict


class RunCancelled(Exception):
    """The run was stopped by user request (POST /runs/{id}/stop) before it
    finished. Not an error -- api/worker.py catches this specifically to
    route to mark_cancelled() instead of mark_failed()."""


def build_config(profile: AnalysisProfile) -> dict:
    """Engine config for a profile.

    Imported lazily: ``tradingagents`` pulls in langchain and the whole vendor
    stack, which is several seconds of import time. A web process that only
    serves /health should not pay that.
    """
    from tradingagents.default_config import DEFAULT_CONFIG, get_fast_config

    config = get_fast_config() if profile is AnalysisProfile.FAST else DEFAULT_CONFIG.copy()
    # Every API-driven run gets a checkpoint, not just ones that end up
    # needing one -- run_analysis()'s resume=False default clears it before
    # each normal run, so this only ever matters when a run actually fails
    # partway through and POST /runs/{id}/resume is used afterward.
    config["checkpoint_enabled"] = True
    return config


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


def _extract_current_price(state: dict) -> float | None:
    """Real last-traded close for the resolved ticker on the analysis date.

    Deliberately NOT read from any model output -- it's a fact, not a
    decision, and the OHLCV data behind it already exists on disk by the
    time this runs: the market analyst fetched (and cached) it during the
    same graph run for this exact (ticker, date), so this call is a cache
    hit in the common case, not a second network round-trip. Uses
    ``company_of_interest`` (set once by ``resolve_ticker_symbol`` in
    ``Propagator.create_initial_state``), not the raw ticker the caller
    passed in -- the raw ticker may be missing its exchange suffix.

    Never raises: a failure here (vendor outage, an asset type with no
    OHLCV concept) must not take down a run that otherwise completed. The
    card just shows "Not set" for current price, same as any other blank
    field.
    """
    from tradingagents.dataflows.stockstats_utils import load_ohlcv

    ticker = state.get("company_of_interest")
    trade_date = state.get("trade_date")
    if not ticker or not trade_date:
        return None
    try:
        data = load_ohlcv(ticker, trade_date)
        if data.empty:
            return None
        return float(data["Close"].iloc[-1])
    except Exception:  # noqa: BLE001 - enrichment only, never fail the run
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

    A Hold rating forces Hold-consistent levels, even if the Trader proposed
    otherwise. The Trader commits to action/entry_price/stop_loss in its OWN
    call, BEFORE the Portfolio Manager runs — it has no way to know the
    Portfolio Manager's eventual rating. The Portfolio Manager's rating is
    documented as "the final position rating" (schemas.PortfolioDecision.
    rating) and reads the Trader's proposal as one input among several (the
    full risk debate too), so it can — correctly, given more context — land
    on Hold after the Trader already proposed a directional trade. Without
    this reconciliation the card could show "Rating: Hold" next to a real
    Buy setup with concrete entry/stop numbers: not a cosmetic label
    mismatch but a conflicting, actionable signal a reader could size a
    position against, exactly contradicting the product's own stated
    contract that a Hold has nothing to size (see TheCall.tsx's levels-
    explanation copy). price_target does NOT need the same treatment: it
    comes from the Portfolio Manager's own call alongside rating, already
    instructed to null it when rating is Hold — self-consistent by
    construction, unlike the Trader's fields. Nulled here regardless, as a
    cheap belt-and-suspenders in case a model ever violates that instruction.
    """
    trader = state.get("trader_investment_plan") or ""
    final = state.get("final_trade_decision") or ""

    rating = _field(final, "Rating")
    action = _field(trader, "Action")
    entry_price = _float_field(trader, "Entry Price")
    stop_loss = _float_field(trader, "Stop Loss")
    position_sizing = _field(trader, "Position Sizing")
    price_target = _float_field(final, "Price Target")

    if rating == "Hold":
        action = "Hold"
        entry_price = None
        stop_loss = None
        position_sizing = None
        price_target = None

    return Verdict(
        rating=rating,
        price_target=price_target,
        time_horizon=_field(final, "Time Horizon"),
        levels=TradeLevels(
            action=action,
            entry_price=entry_price,
            stop_loss=stop_loss,
            position_sizing=position_sizing,
        ),
        current_price=_extract_current_price(state),
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
    on_token=None,
    should_stop=None,
    time_horizon: str | None = None,
    resume: bool = False,
) -> tuple[Verdict, Reports]:
    """Execute one full analysis. Blocking, minutes long, worker-only.

    Note the engine freezes its own inputs per (ticker, date) via
    ``dataflows.snapshot_cache``, so a second run of the same ticker and date
    re-uses the first run's news, filings and market snapshot and only repeats
    the LLM reasoning. That is a separate layer from the run cache above it,
    which skips the reasoning too.

    ``on_token``, when given, switches the engine call from ``propagate`` to
    ``propagate_streaming`` so token deltas are emitted as a side effect while
    the analysis runs. ``propagate()`` returns a ``(final_state, signal)``
    tuple; ``propagate_streaming()`` returns just ``final_state`` — an
    intentional, documented difference (see the engine's
    ``propagate_streaming`` docstring), not unified here.

    ``should_stop``, when given, is threaded through to ``propagate_streaming``
    (only meaningful there — the non-streaming ``propagate()`` path has no
    per-chunk checkpoint to attach it to). Raises ``RunCancelled`` instead of
    returning if the run was stopped, translated here from the engine's own
    ``StreamCancelled`` so nothing outside this module needs to import
    from ``tradingagents`` directly (this module's own docstring: it is the
    sole seam between the HTTP layer and the engine).

    ``time_horizon``, when given, is forwarded as ``investment_horizon`` to
    the engine, which threads it into state for the Portfolio Manager only —
    it does not change what data the analysts fetch or read.

    ``resume``, default False: forwarded to the engine's own ``resume``
    parameter (see ``TradingAgentsGraph.propagate_streaming``). False (every
    normal call, including a plain retry) clears any leftover checkpoint for
    this (ticker, date) before starting, so a fresh run never silently
    inherits state from an unrelated earlier attempt. Only
    ``POST /runs/{id}/resume`` sets this True, and only for a run that was
    itself ``failed`` — see ``SqlRunStore.create_resume``.
    """
    from tradingagents.graph.trading_graph import StreamCancelled, TradingAgentsGraph

    config = build_config(profile)
    # refresh_data=True busts the day's snapshot so news/filings/social are
    # re-fetched. Left False, a repeat run re-reasons over IDENTICAL inputs,
    # which is what makes two runs comparable — any difference is the model,
    # not the data.
    config["snapshot_cache_enabled"] = not refresh_data

    graph = TradingAgentsGraph(config=config)
    if on_token is not None:
        try:
            final_state = graph.propagate_streaming(
                ticker,
                str(analysis_date),
                on_token=on_token,
                should_stop=should_stop,
                investment_horizon=time_horizon,
                resume=resume,
            )
        except StreamCancelled as exc:
            raise RunCancelled(str(exc)) from exc
    else:
        final_state, _signal = graph.propagate(
            ticker, str(analysis_date), investment_horizon=time_horizon, resume=resume
        )

    return _extract_verdict(final_state), _extract_reports(final_state)
