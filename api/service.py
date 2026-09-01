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

import logging
from datetime import date as Date

from api.schemas import AnalysisProfile, Reports, TradeLevels, Verdict

logger = logging.getLogger(__name__)


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


# A stop closer to its entry than this fraction of ATR is treated as not a
# real stop. SKYGOLD.NS 2026-08-31, one run before the one that got the
# level right: entry 777 / stop 765 -- a 12-point gap against that day's
# ATR of 33.69, i.e. 0.36 ATR. Ordinary intraday noise clears that distance
# without the thesis being wrong at all, so the "protection" it offered was
# closer to a coin flip than a risk boundary. 0.5x is deliberately a FLOOR,
# not a target: this product's horizons run 3-6+ months (a swing/position
# style, not intraday scalping, where a sub-ATR stop can be a deliberate,
# tight choice), so a stop this close to entry on a multi-month call is far
# more likely an anchoring slip than a considered decision.
_MIN_STOP_ATR_MULTIPLE = 0.5


def _extract_atr(state: dict) -> float | None:
    """Average True Range for the resolved ticker on the analysis date.

    Reuses market_data_validator._calculate_latest_indicators against the
    SAME load_ohlcv data _extract_current_price already fetched (a cache
    hit, not a second computation path), so this can never disagree with
    the verified market snapshot's own ATR value -- and it inherits that
    function's minimum-history guard for free, so a young listing where ATR
    "not computable (needs 14 sessions, ...)" correctly yields None here
    too rather than a value nobody can trust.

    Never raises. Returns None whenever ATR is unavailable for any reason
    (short history, a vendor outage, a data shape wrap() rejects): the
    guard that consumes this treats None as "cannot judge, so do not guard"
    rather than as a reason to fail or discard anything.
    """
    from tradingagents.dataflows.market_data_validator import _calculate_latest_indicators
    from tradingagents.dataflows.stockstats_utils import load_ohlcv

    ticker = state.get("company_of_interest")
    trade_date = state.get("trade_date")
    if not ticker or not trade_date:
        return None
    try:
        data = load_ohlcv(ticker, trade_date)
        if data.empty:
            return None
        atr = _calculate_latest_indicators(data).get("atr")
        if not isinstance(atr, (int, float)) or atr != atr:  # NaN != NaN
            return None
        return float(atr)
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

    The RATING decides which of entry/stop/exit are shown at all, on top of
    everything above being resolved first. This is enforced here regardless
    of what the Trader or Portfolio Manager produced, the same
    belt-and-suspenders reasoning as the Hold case below: schemas.py's own
    field descriptions already tell the model the same rule (so a
    well-behaved model rarely trips this), but the guarantee the user sees
    has to hold even if a model doesn't follow it.

      Hold                -- none of entry/stop/exit apply. The Trader
                             commits to action/entry_price/stop_loss in its
                             OWN call, BEFORE the Portfolio Manager runs —
                             it has no way to know the Portfolio Manager's
                             eventual rating, which is documented as "the
                             final position rating" and can, correctly,
                             land on Hold after the Trader already proposed
                             a directional trade. Without this the card
                             could show "Rating: Hold" next to a real Buy
                             setup with concrete entry/stop numbers: not a
                             cosmetic mismatch but a conflicting,
                             actionable signal a reader could size a
                             position against, contradicting the product's
                             own stated contract that a Hold has nothing to
                             size (TheCall.tsx's levels-explanation copy).
      Overweight (add)    -- only entry applies. This is a tactical add to
                             an existing/core position, not a fresh full
                             trade: there is no new stop to set (the risk
                             sits on the core holding this is layered onto,
                             not on the add itself) and no exit/target
                             (you are growing exposure, not defining where
                             to close it).
      Underweight (trim)  -- only exit (price_target) applies. There is
                             nothing to enter (you already hold the
                             position) and no fresh stop to set (a position
                             being reduced is being reduced, not
                             protected) — the level that remains meaningful
                             is where you trim INTO.
      Buy / Sell          -- entry, stop, and exit all apply; a full trade
                             with nothing rating-specific to null.
    """
    trader = state.get("trader_investment_plan") or ""
    final = state.get("final_trade_decision") or ""

    rating = _field(final, "Rating")
    action = _field(trader, "Action")
    position_sizing = _field(trader, "Position Sizing")
    price_target = _float_field(final, "Price Target")
    current_price = _extract_current_price(state)

    # The Portfolio Manager's own levels win when it supplied them. It rules
    # last, having read the Trader's proposal AND the full risk debate, and
    # it routinely works out better levels than the Trader had -- SKYGOLD.NS
    # 2026-08-31: "trim toward the 843-850 resistance zone ... hard-stop
    # near 770-774" against an 811.40 close, while the Trader's fields said
    # entry 5000 / stop 4200. Falls back to the Trader's whenever the PM
    # left a field null, which is the previous behaviour exactly, so a PM
    # with nothing to correct changes nothing.
    entry_price = _float_field(final, "PM Entry Price")
    if entry_price is None:
        entry_price = _float_field(trader, "Entry Price")
    stop_loss = _float_field(final, "PM Stop Loss")
    if stop_loss is None:
        stop_loss = _float_field(trader, "Stop Loss")

    # Last-resort guard on a level that cannot be transacted at. Both known
    # failures were an order of magnitude out (SKYGOLD entry 5000 vs an 811
    # close and a 848 52-week high; KAYNES entry 2600 vs 3943), and both
    # passed the schema's own check because that only compares stop to entry
    # and never to the market. Bounds are deliberately WIDE -- half to double
    # the last close -- so every legitimate setup survives: a deep pullback
    # entry, a breakout above resistance, a stop under a distant support all
    # sit comfortably inside. This is not a view on whether a level is good,
    # only on whether it belongs to this instrument at all.
    #
    # Drops rather than clamps, following TraderProposal.
    # _drop_incoherent_levels: inventing a "corrected" number would be
    # asserting a level nobody proposed, and a blank field already renders
    # as "Not set" (DEV_HANDOFF.md: a blank field is meaningful).
    if current_price is not None and current_price > 0:
        lo, hi = current_price * 0.5, current_price * 2.0
        if entry_price is not None and not (lo <= entry_price <= hi):
            logger.warning(
                "Discarding entry_price %.2f: outside %.2f-%.2f around last close %.2f",
                entry_price, lo, hi, current_price,
            )
            entry_price = None
        if stop_loss is not None and not (lo <= stop_loss <= hi):
            logger.warning(
                "Discarding stop_loss %.2f: outside %.2f-%.2f around last close %.2f",
                stop_loss, lo, hi, current_price,
            )
            stop_loss = None
        # A stop only means anything against an entry; if the entry was the
        # implausible one, a surviving stop is orphaned rather than useful.
        if entry_price is None and stop_loss is not None:
            stop_loss = None

    # A stop can pass the two checks above (below entry, in the right
    # ballpark) and still not function as a stop: SKYGOLD.NS 2026-08-31,
    # entry 777 / stop 765, is 12 points against that day's ATR of 33.69 --
    # 0.36 ATR, well inside a single session's ordinary noise. Only the
    # stop is dropped, following the same "drop the questionable field, not
    # the whole level pair" rule as the guard above: the entry itself is
    # unaffected, since a too-tight stop says nothing about whether the
    # entry level was well chosen.
    if entry_price is not None and stop_loss is not None:
        atr = _extract_atr(state)
        if atr is not None and atr > 0:
            min_distance = atr * _MIN_STOP_ATR_MULTIPLE
            if abs(entry_price - stop_loss) < min_distance:
                logger.warning(
                    "Discarding stop_loss %.2f: %.2f from entry %.2f, "
                    "under %.2fx ATR (%.2f)",
                    stop_loss, abs(entry_price - stop_loss), entry_price,
                    _MIN_STOP_ATR_MULTIPLE, atr,
                )
                stop_loss = None

    if rating == "Hold":
        action = "Hold"
        entry_price = None
        stop_loss = None
        position_sizing = None
        price_target = None
    elif rating == "Overweight":
        # A tactical add to an existing/core position, not a fresh full
        # trade: entry (where to add) is the only level that means
        # anything here.
        stop_loss = None
        price_target = None
    elif rating == "Underweight":
        # A trim of an existing position, not a fresh trade: exit (where
        # to trim into) is the only level that means anything here.
        entry_price = None
        stop_loss = None

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
        current_price=current_price,
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
