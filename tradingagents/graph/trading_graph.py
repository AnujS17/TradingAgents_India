# TradingAgents/graph/trading_graph.py

import logging
import os
from pathlib import Path
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple, List, Optional

import yfinance as yf
from langchain_core.messages import AIMessage, ToolMessage

logger = logging.getLogger(__name__)

from langgraph.prebuilt import ToolNode

from tradingagents.llm_clients import create_llm_client

from tradingagents.agents import *
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.dataflows.utils import safe_ticker_component
from tradingagents.agents.utils.agent_states import (
    AgentState,
    InvestDebateState,
    RiskDebateState,
)
from tradingagents.dataflows.config import set_config

# Import the new abstract tool methods from agent_utils
from tradingagents.agents.utils.agent_utils import (
    get_stock_data,
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement,
    get_news,
    get_insider_transactions,
    get_global_news,
    resolve_ticker_symbol,
)

from .checkpointer import checkpoint_step, clear_checkpoint, get_checkpointer, thread_id
from .conditional_logic import ConditionalLogic
from .setup import GraphSetup
from .propagation import Propagator
from .reflection import Reflector
from .signal_processing import SignalProcessor


def _canonical_tool_args(args: Any) -> str:
    """Stable key for tool-call arguments."""
    try:
        return json.dumps(args or {}, sort_keys=True, default=str)
    except TypeError:
        return str(args)


def _find_prior_tool_result(messages: list, tool_name: str, args: Any, current_call_id: str) -> Optional[str]:
    target_args = _canonical_tool_args(args)
    seen_call_ids: set[str] = set()
    duplicate_call_ids: set[str] = set()

    for message in messages[:-1]:
        if isinstance(message, AIMessage):
            for call in message.tool_calls or []:
                call_id = call.get("id")
                if call_id == current_call_id:
                    continue
                if call.get("name") == tool_name and _canonical_tool_args(call.get("args")) == target_args:
                    if call_id:
                        duplicate_call_ids.add(call_id)
                if call_id:
                    seen_call_ids.add(call_id)
            continue

        if isinstance(message, ToolMessage) and message.tool_call_id in duplicate_call_ids:
            content = message.content
            if isinstance(content, str) and content.strip():
                return content
            return str(content)

    return None


def _dedupe_tool_call(request, execute):
    """Short-circuit identical tool calls already answered in this analyst turn."""
    call = request.tool_call
    state = request.state if isinstance(request.state, dict) else {}
    # Search every analyst channel, not just "messages": each analyst now
    # owns its own (see AgentState), so looking only at the shared channel
    # would find nothing and silently turn this dedupe into a no-op.
    all_messages = []
    for key in ("messages", "market_messages", "sentiment_messages",
                "news_messages", "fundamentals_messages"):
        all_messages.extend(state.get(key) or [])
    prior = _find_prior_tool_result(
        all_messages,
        call.get("name", ""),
        call.get("args", {}),
        call.get("id", ""),
    )
    if prior is None:
        return execute(request)

    return ToolMessage(
        content=(
            "Duplicate tool call skipped: this exact tool name and arguments "
            "were already executed earlier in the current analyst turn. Use the "
            "previous ToolMessage result already present in the conversation "
            "instead of fetching it again."
        ),
        name=call.get("name"),
        tool_call_id=call.get("id"),
    )


def apply_openrouter_variant(model: str, provider: str, exacto: bool) -> str:
    """Append OpenRouter's ``:exacto`` variant to a model slug when enabled.

    Exacto is a quality-first provider SORT: OpenRouter ranks upstreams by
    real tool-calling success rates and its own benchmark harness, then
    deprioritises the weak ones. It matters here because langchain's
    ``with_structured_output()`` drives structured output through tool
    calling -- the capability that was returning empty prose fields (see
    default_config.py's OpenRouter provider-routing block).

    Left alone in three cases, each of which would otherwise produce a slug
    OpenRouter rejects or silently mis-routes:

    * a non-openrouter provider, whose slugs have no variant concept at all;
    * a slug that already carries a variant (``:free``, ``:nitro``,
      ``:floor``, ``:exacto``) -- variants do not stack, and the catalog
      really does ship one (``poolside/laguna-m.1:free``), so appending
      would yield ``...:free:exacto``;
    * an empty/None model, left for the client layer to report.

    The variant is detected after the last ``/`` so a vendor segment can
    never be mistaken for one.
    """
    if not exacto or not model or provider.lower() != "openrouter":
        return model
    if ":" in model.rsplit("/", 1)[-1]:
        return model
    return f"{model}:exacto"


class StreamCancelled(Exception):
    """Raised by propagate_streaming() when should_stop() reports true
    between streamed chunks. Not an error -- a deliberate stop request.

    api/service.py (the only module outside tradingagents that imports it)
    catches this and translates it to its own RunCancelled before it
    reaches api/worker.py, so nothing outside tradingagents ever needs to
    import from here directly (api/service.py's own module docstring: it
    is the sole seam between the HTTP layer and the engine)."""


class TradingAgentsGraph:
    """Main class that orchestrates the trading agents framework."""

    def __init__(
        self,
        selected_analysts=["market", "social", "news", "fundamentals"],
        debug=False,
        config: Dict[str, Any] = None,
        callbacks: Optional[List] = None,
    ):
        """Initialize the trading agents graph and components.

        Args:
            selected_analysts: List of analyst types to include
            debug: Whether to run in debug mode
            config: Configuration dictionary. If None, uses default config
            callbacks: Optional list of callback handlers (e.g., for tracking LLM/tool stats)
        """
        self.debug = debug
        self.config = config or DEFAULT_CONFIG
        self.callbacks = callbacks or []

        # Update the interface's config
        set_config(self.config)

        # Create necessary directories
        os.makedirs(self.config["data_cache_dir"], exist_ok=True)
        os.makedirs(self.config["results_dir"], exist_ok=True)

        # Initialize LLMs with provider-specific thinking configuration
        llm_kwargs = self._get_provider_kwargs()

        # Add callbacks to kwargs if provided (passed to LLM constructor)
        if self.callbacks:
            llm_kwargs["callbacks"] = self.callbacks

        _provider = self.config["llm_provider"]
        _exacto = self.config.get("openrouter_exacto", False)

        deep_client = create_llm_client(
            provider=_provider,
            model=apply_openrouter_variant(
                self.config["deep_think_llm"], _provider, _exacto
            ),
            base_url=self.config.get("backend_url"),
            **llm_kwargs,
        )
        quick_client = create_llm_client(
            provider=_provider,
            model=apply_openrouter_variant(
                self.config["quick_think_llm"], _provider, _exacto
            ),
            base_url=self.config.get("backend_url"),
            **llm_kwargs,
        )

        self.deep_thinking_llm = deep_client.get_llm()
        self.quick_thinking_llm = quick_client.get_llm()
        
        self.memory_log = TradingMemoryLog(self.config)

        # Create tool nodes
        self.tool_nodes = self._create_tool_nodes()

        # Initialize components
        self.conditional_logic = ConditionalLogic(
            max_debate_rounds=self.config["max_debate_rounds"],
            max_risk_discuss_rounds=self.config["max_risk_discuss_rounds"],
        )
        self.graph_setup = GraphSetup(
            self.quick_thinking_llm,
            self.deep_thinking_llm,
            self.tool_nodes,
            self.conditional_logic,
            analyst_concurrency_limit=self.config.get("analyst_concurrency_limit", 1),
        )

        self.propagator = Propagator(
            max_recur_limit=self.config.get("max_recur_limit", 100),
        )
        self.reflector = Reflector(self.quick_thinking_llm)
        self.signal_processor = SignalProcessor(self.quick_thinking_llm)

        # State tracking
        self.curr_state = None
        self.ticker = None
        self.log_states_dict = {}  # date to full state dict

        # Set up the graph: keep the workflow for recompilation with a checkpointer.
        self.workflow = self.graph_setup.setup_graph(selected_analysts)
        self.graph = self.workflow.compile()
        self._checkpointer_ctx = None

    def _get_provider_kwargs(self) -> Dict[str, Any]:
        """Get provider-specific kwargs for LLM client creation."""
        kwargs = {}
        provider = self.config.get("llm_provider", "").lower()

        # Universal output-token ceiling. Each provider spells this
        # differently, so it is mapped here rather than pushed into every
        # client: Google's SDK uses max_output_tokens; Anthropic and every
        # OpenAI-compatible Chat Completions provider (deepseek — the
        # default — plus xai/qwen/glm/minimax/ollama) use max_tokens.
        # openrouter is excluded because it already has its own
        # openrouter_max_completion_tokens set further down; setting both
        # would be ambiguous about which wins.
        max_output_tokens = self.config.get("max_output_tokens")
        if max_output_tokens and provider != "openrouter":
            token_kwarg = "max_output_tokens" if provider == "google" else "max_tokens"
            kwargs[token_kwarg] = int(max_output_tokens)

        # Sampling controls, applied to EVERY provider.
        #
        # Previously only openrouter got temperature/top_p, so every other
        # provider ran at its own default (~1.0) with no seed — two identical
        # runs could and did reach opposite verdicts (LICI.NS 2026-08-11: two
        # default-config runs 12 minutes apart returned HOLD then BUY on the
        # same data).
        #
        # This REDUCES variance, it does not eliminate it: no major provider
        # guarantees bitwise reproducibility, because batching and MoE routing
        # shift results regardless of seed. Treat it as narrowing the spread,
        # not as making runs identical.
        #
        # openrouter keeps its own openrouter_temperature/_top_p below so the
        # two knobs cannot fight; only the seed is shared with it.
        temperature = self.config.get("llm_temperature")
        if temperature is not None and provider != "openrouter":
            kwargs["temperature"] = float(temperature)

        # Anthropic and Google expose no seed parameter, so this is silently a
        # no-op there — the temperature above is the only lever for them.
        seed = self.config.get("llm_seed")
        if seed is not None and provider not in ("anthropic", "google"):
            kwargs["seed"] = int(seed)

        # Every provider client (openai_client, anthropic_client,
        # google_client, azure_client) forwards `timeout` straight through
        # to its underlying SDK -- see each client's _PASSTHROUGH_KWARGS.
        # Bounds a single call's worst case; see default_config.py's
        # llm_timeout_seconds comment for the incident that motivated this.
        timeout = self.config.get("llm_timeout_seconds")
        if timeout is not None:
            kwargs["timeout"] = float(timeout)

        if provider == "google":
            thinking_level = self.config.get("google_thinking_level")
            if thinking_level:
                kwargs["thinking_level"] = thinking_level

        elif provider == "openai":
            reasoning_effort = self.config.get("openai_reasoning_effort")
            if reasoning_effort:
                kwargs["reasoning_effort"] = reasoning_effort

        elif provider == "anthropic":
            effort = self.config.get("anthropic_effort")
            if effort:
                kwargs["effort"] = effort
        elif provider == "openrouter":
            # Built up across both blocks below, then attached once. It used
            # to be created inside `if effort:`, which meant an unset
            # openrouter_reasoning_effort silently discarded everything else
            # that belongs in extra_body -- including the provider routing.
            extra_body: Dict[str, Any] = {}

            effort = self.config.get("openrouter_reasoning_effort")
            if effort:
                # OpenRouter's OpenAI-compatible chat endpoint accepts
                # reasoning controls in extra_body. Passing top-level
                # reasoning_effort can make langchain route through the
                # OpenAI Responses API shape, which OpenRouter rejects.
                extra_body["reasoning"] = {
                    "effort": effort,
                    # Keep provider reasoning out of saved reports/logs
                    # while still allowing internal reasoning tokens.
                    "exclude": True,
                }

            # Provider routing. See default_config.py's own block for the
            # incident and the measured provider capabilities behind these.
            # Deliberately NO require_parameters: langchain always sends
            # max_completion_tokens and parallel_tool_calls, which no
            # endpoint advertises, so it matches zero endpoints and 404s
            # every call. The `only` allowlist carries the capability
            # guarantee instead -- see default_config.py for the evidence.
            provider_prefs: Dict[str, Any] = {}
            quantizations = self.config.get("openrouter_quantizations")
            if quantizations:
                provider_prefs["quantizations"] = list(quantizations)
            only_providers = self.config.get("openrouter_only_providers")
            if only_providers:
                provider_prefs["only"] = list(only_providers)
            if provider_prefs:
                extra_body["provider"] = provider_prefs

            if extra_body:
                kwargs["extra_body"] = extra_body

            max_completion_tokens = self.config.get("openrouter_max_completion_tokens")
            if max_completion_tokens:
                kwargs["max_completion_tokens"] = int(max_completion_tokens)
            temperature = self.config.get("openrouter_temperature")
            if temperature is not None:
                kwargs["temperature"] = float(temperature)
            top_p = self.config.get("openrouter_top_p")
            if top_p is not None:
                kwargs["top_p"] = float(top_p)

        return kwargs

    def _create_tool_nodes(self) -> Dict[str, ToolNode]:
        """Create tool nodes for different data sources using abstract methods."""
        return {
            "market": ToolNode(
                [
                    # Core stock data tools
                    get_stock_data,
                    # get_indicators and get_verified_market_snapshot are NOT
                    # registered here — both are pre-fetched directly in
                    # market_analyst.py (the verified snapshot now includes
                    # an Indicator Trend section covering what get_indicators
                    # used to be called for) and never offered to the LLM via
                    # bind_tools, so a tool node entry would be unreachable
                    # dead capacity.
                ],
                messages_key="market_messages",
                wrap_tool_call=_dedupe_tool_call,
            ),
            "social": ToolNode(
                [
                    # News tools for social media analysis
                    get_news,
                ],
                messages_key="sentiment_messages",
                wrap_tool_call=_dedupe_tool_call,
            ),
            "news": ToolNode(
                [
                    # News and insider information
                    get_news,
                    get_global_news,
                    get_insider_transactions,
                ],
                messages_key="news_messages",
                wrap_tool_call=_dedupe_tool_call,
            ),
            "fundamentals": ToolNode(
                [
                    # Fundamental analysis tools
                    get_fundamentals,
                    get_balance_sheet,
                    get_cashflow,
                    get_income_statement,
                    # ETF fundamentals analysts use news context instead of
                    # company financial statements.
                    get_news,
                    get_global_news,
                ],
                messages_key="fundamentals_messages",
                wrap_tool_call=_dedupe_tool_call,
            ),
        }

    def _resolve_benchmark(self, ticker: str) -> str:
        """Pick the benchmark ticker for alpha calculation against ``ticker``.

        ``config["benchmark_ticker"]`` overrides everything when set; otherwise
        the suffix map matches the ticker's exchange suffix (e.g. ``.NS`` for
        NSE, ``.T`` for Tokyo). US-listed tickers without a dotted suffix fall
        through to the empty-suffix entry (SPY by default). Unrecognised
        suffixes (including US tickers with dots like ``BRK.B``) also fall
        back to the empty-suffix entry — return-percentage math is
        currency-agnostic, so SPY is just a reasonable generic equity
        benchmark for tickers with no recognised exchange suffix.
        """
        explicit = self.config.get("benchmark_ticker")
        if explicit:
            return explicit
        benchmark_map = self.config.get("benchmark_map", {})
        ticker_upper = ticker.upper()
        for suffix, benchmark in benchmark_map.items():
            if suffix and ticker_upper.endswith(suffix.upper()):
                return benchmark
        return benchmark_map.get("", "SPY")

    def _fetch_returns(
        self, ticker: str, trade_date: str, holding_days: int = 5,
        benchmark: str = "SPY",
    ) -> Tuple[Optional[float], Optional[float], Optional[int]]:
        """Fetch raw and alpha return for ticker over holding_days from trade_date.

        ``benchmark`` is the index used as the alpha baseline (resolved by the
        caller via ``_resolve_benchmark``). Returns ``(raw_return, alpha_return,
        actual_holding_days)`` or ``(None, None, None)`` if price data is
        unavailable (too recent, delisted, or network error).
        """
        try:
            start = datetime.strptime(trade_date, "%Y-%m-%d")
            end = start + timedelta(days=holding_days + 7)  # buffer for weekends/holidays
            end_str = end.strftime("%Y-%m-%d")

            stock = yf.Ticker(ticker).history(start=trade_date, end=end_str)
            bench = yf.Ticker(benchmark).history(start=trade_date, end=end_str)

            if len(stock) < 2 or len(bench) < 2:
                return None, None, None

            actual_days = min(holding_days, len(stock) - 1, len(bench) - 1)
            raw = float(
                (stock["Close"].iloc[actual_days] - stock["Close"].iloc[0])
                / stock["Close"].iloc[0]
            )
            bench_ret = float(
                (bench["Close"].iloc[actual_days] - bench["Close"].iloc[0])
                / bench["Close"].iloc[0]
            )
            alpha = raw - bench_ret
            return raw, alpha, actual_days
        except Exception as e:
            logger.warning(
                "Could not resolve outcome for %s on %s vs %s (will retry next run): %s",
                ticker, trade_date, benchmark, e,
            )
            return None, None, None

    def _resolve_pending_entries(self, ticker: str) -> None:
        """Resolve pending log entries for ticker at the start of a new run.

        Fetches returns for each same-ticker pending entry, generates reflections,
        then writes all updates in a single atomic batch write to avoid redundant I/O.
        Skips entries whose price data is not yet available (too recent or delisted).

        Trade-off: only same-ticker entries are resolved per run.  Entries for
        other tickers accumulate until that ticker is run again.
        """
        pending = [e for e in self.memory_log.get_pending_entries() if e["ticker"] == ticker]
        if not pending:
            return

        benchmark = self._resolve_benchmark(ticker)
        updates = []
        for entry in pending:
            raw, alpha, days = self._fetch_returns(
                ticker, entry["date"], benchmark=benchmark,
            )
            if raw is None:
                continue  # price not available yet — try again next run
            reflection = self.reflector.reflect_on_final_decision(
                final_decision=entry.get("decision", ""),
                raw_return=raw,
                alpha_return=alpha,
                benchmark_name=benchmark,
            )
            updates.append({
                "ticker": ticker,
                "trade_date": entry["date"],
                "raw_return": raw,
                "alpha_return": alpha,
                "holding_days": days,
                "reflection": reflection,
            })

        if updates:
            self.memory_log.batch_update_with_outcomes(updates)

    def propagate(
        self,
        company_name,
        trade_date,
        asset_type: str = "stock",
        investment_horizon: str | None = None,
        resume: bool = False,
    ):
        """Run the trading agents graph for a company on a specific date.

        ``asset_type`` selects between the stock pipeline (default) and the
        crypto pipeline (``"crypto"``) shipped in #567 — the CLI auto-detects
        from the ticker; programmatic callers pass it explicitly. When
        ``checkpoint_enabled`` is set in config, the graph is recompiled with
        a per-ticker SqliteSaver so a crashed run can resume from the last
        successful node on a subsequent invocation with the same ticker+date.

        ``investment_horizon``, when given, is optional holding-period
        guidance for the Portfolio Manager only (see
        ``Propagator.create_initial_state``) — it does not affect what any
        analyst fetches or reads.

        ``resume``, default False: whether this call may pick up an existing
        checkpoint for (company_name, trade_date). A checkpoint is keyed on
        that pair alone, not on a specific caller or run id, so every call
        that does NOT explicitly ask to resume clears any leftover checkpoint
        before starting — otherwise a deliberate fresh run (e.g. re-running
        the same ticker+date to compare two models) would silently inherit a
        stale in-progress state from an unrelated earlier attempt instead of
        genuinely starting over.
        """
        # Resolve the ticker once, here, before anything keys off it. Every
        # identity in this method is derived from company_name: self.ticker
        # (which names the state-log directory), the memory-log key, and the
        # checkpoint thread id. Resolution used to happen further down in
        # create_initial_state(), so a caller passing "BLUEJET" analysed
        # BLUEJET.NS while its logs, memory entries and checkpoint were all
        # filed under "BLUEJET" — the same company under two identities
        # depending on how it was typed, splitting the per-ticker history that
        # deferred reflection reads back. lru_cached, so create_initial_state's
        # own call returns this identical value at no extra cost.
        company_name = resolve_ticker_symbol(company_name, asset_type)
        self.ticker = company_name

        # Freeze the data layer for this (ticker, date). Every news/social/
        # filings fetcher is wrapped in snapshot_cached, which is a no-op until
        # this key is set — so re-running the same ticker on the same date
        # replays byte-identical inputs instead of re-pulling a rolling news
        # feed. Measured before this: 22 of 63 headlines changed between two
        # SIEMENS.NS runs 11 minutes apart with the market closed. Both the
        # module-level config and self.config are set because the dataflows
        # layer reads the former while this class reads the latter.
        from tradingagents.dataflows.snapshot_cache import set_snapshot_date

        set_snapshot_date(trade_date)

        # Resolve any pending memory-log entries for this ticker before the pipeline runs.
        self._resolve_pending_entries(company_name)

        # Recompile with a checkpointer if the user opted in.
        if self.config.get("checkpoint_enabled"):
            if not resume:
                clear_checkpoint(self.config["data_cache_dir"], company_name, str(trade_date))

            self._checkpointer_ctx = get_checkpointer(
                self.config["data_cache_dir"], company_name
            )
            saver = self._checkpointer_ctx.__enter__()
            self.graph = self.workflow.compile(checkpointer=saver)

            step = checkpoint_step(
                self.config["data_cache_dir"], company_name, str(trade_date)
            )
            if step is not None:
                logger.info(
                    "Resuming from step %d for %s on %s", step, company_name, trade_date
                )
            else:
                logger.info("Starting fresh for %s on %s", company_name, trade_date)

        try:
            return self._run_graph(
                company_name, trade_date, asset_type=asset_type, investment_horizon=investment_horizon
            )
        finally:
            if self._checkpointer_ctx is not None:
                self._checkpointer_ctx.__exit__(None, None, None)
                self._checkpointer_ctx = None
                self.graph = self.workflow.compile()

    def propagate_streaming(
        self,
        company_name,
        trade_date,
        asset_type: str = "stock",
        on_token=None,
        should_stop=None,
        investment_horizon: str | None = None,
        resume: bool = False,
    ):
        """Like propagate(), but also streams token-level chunks through
        on_token(node_name: str, delta: str) as the graph executes.

        ``resume``: see propagate()'s docstring -- same contract, same
        default. False (every normal call) clears any leftover checkpoint
        for (company_name, trade_date) before starting; True lets an
        existing checkpoint from a prior crashed attempt be picked up.

        on_token is optional; passing None runs identically to propagate()
        with no callback overhead beyond the extra stream_mode. on_token is
        never allowed to raise into this method's control flow -- a failing
        callback degrades to "no live view for that chunk," never fails the
        run itself (see docs/superpowers/specs/2026-08-19-live-streaming-design.md).

        should_stop, when given, is called once per streamed chunk (both
        stream_mode="values" node-completions and stream_mode="messages"
        token deltas -- so typically once per token, not once per node) and,
        if it returns true, raises StreamCancelled to unwind the graph.stream()
        generator early. This is cooperative cancellation, not a kill signal:
        an in-flight LLM call for the currently-executing node still runs to
        that call's own completion before the next chunk (and therefore the
        next check) arrives -- there is no way to interrupt a call already in
        flight without the node itself checking. In practice this resolves
        within about one token's latency because "messages" mode yields far
        more often than "values" mode does.

        Returns the merged final-state dict (the same final_state propagate()
        builds internally before pairing it with a processed signal) -- not
        propagate()'s own (final_state, signal) tuple, since callers of this
        streaming path only need the state.

        Does NOT modify propagate()/_run_graph() -- this is a parallel,
        additive execution path for the worker's streaming call site only.
        """
        # Same ticker-resolution/snapshot/memory-log setup _run_graph() uses
        # (see propagate()'s comments above for why each step is ordered
        # this way); duplicated rather than factored out to avoid touching
        # the tuned, working propagate()/_run_graph() path.
        company_name = resolve_ticker_symbol(company_name, asset_type)
        self.ticker = company_name

        from tradingagents.dataflows.snapshot_cache import set_snapshot_date

        set_snapshot_date(trade_date)
        self._resolve_pending_entries(company_name)

        # Recompile with a checkpointer if opted in -- same mechanism
        # propagate()/_run_graph() uses, previously never reached from here,
        # which is why a worker crash mid-stream (the only path api.worker
        # actually calls) never had anything to resume from.
        if self.config.get("checkpoint_enabled"):
            if not resume:
                clear_checkpoint(self.config["data_cache_dir"], company_name, str(trade_date))

            self._checkpointer_ctx = get_checkpointer(
                self.config["data_cache_dir"], company_name
            )
            saver = self._checkpointer_ctx.__enter__()
            self.graph = self.workflow.compile(checkpointer=saver)

        past_context = self.memory_log.get_past_context(company_name)
        init_agent_state = self.propagator.create_initial_state(
            company_name,
            trade_date,
            asset_type=asset_type,
            past_context=past_context,
            investment_horizon=investment_horizon,
        )
        args = self.propagator.get_graph_args()
        args.pop("stream_mode", None)  # this method controls stream_mode itself

        # graph_input is None on a genuine resume, NOT init_agent_state --
        # see the identical comment and empirical verification in
        # _run_graph(). Passing the full initial state again would make
        # LangGraph re-apply it as a fresh update over the checkpoint,
        # re-running every already-completed node instead of skipping them.
        graph_input = init_agent_state
        resuming = False
        if self.config.get("checkpoint_enabled"):
            tid = thread_id(company_name, str(trade_date))
            args.setdefault("config", {}).setdefault("configurable", {})["thread_id"] = tid
            resuming = (
                checkpoint_step(self.config["data_cache_dir"], company_name, str(trade_date))
                is not None
            )
            if resuming:
                graph_input = None
            logger.info(
                "%s (streaming) for %s on %s",
                "Resuming" if resuming else "Starting fresh",
                company_name,
                trade_date,
            )

        final_state: dict = {}
        try:
            for stream_mode, chunk in self.graph.stream(
                graph_input, stream_mode=["values", "messages"], **args
            ):
                if should_stop is not None and should_stop():
                    raise StreamCancelled(f"{company_name} analysis stopped by request")
                if stream_mode == "values":
                    final_state.update(chunk)
                elif stream_mode == "messages" and on_token is not None:
                    message_chunk, metadata = chunk
                    node_name = metadata.get("langgraph_node", "unknown")
                    delta = getattr(message_chunk, "content", "") or ""
                    if delta:
                        try:
                            on_token(node_name, delta)
                        except Exception as exc:  # noqa: BLE001 - never fail the run over a live-view glitch
                            logger.warning("propagate_streaming: on_token failed (%s)", exc)
        finally:
            if self._checkpointer_ctx is not None:
                self._checkpointer_ctx.__exit__(None, None, None)
                self._checkpointer_ctx = None
                self.graph = self.workflow.compile()

        # Clear the checkpoint on successful completion (mirrors
        # _run_graph()) so a later, unrelated run for the same ticker+date
        # doesn't see stale state. A StreamCancelled/exception above skips
        # this, leaving the checkpoint in place for the next attempt to
        # resume from -- the entire point of this feature.
        if self.config.get("checkpoint_enabled"):
            clear_checkpoint(self.config["data_cache_dir"], company_name, str(trade_date))

        self.curr_state = final_state
        self._log_state(trade_date, final_state)
        return final_state

    def _run_graph(
        self, company_name, trade_date, asset_type: str = "stock", investment_horizon: str | None = None
    ):
        """Execute the graph and write the resulting state to disk and memory log."""
        # Initialize state — inject memory log context for PM.
        past_context = self.memory_log.get_past_context(company_name)
        init_agent_state = self.propagator.create_initial_state(
            company_name,
            trade_date,
            asset_type=asset_type,
            past_context=past_context,
            investment_horizon=investment_horizon,
        )
        args = self.propagator.get_graph_args()

        # Inject thread_id so same ticker+date resumes, different date starts fresh.
        #
        # graph_input is None on a genuine resume, NOT init_agent_state. This
        # used to always pass init_agent_state, which defeated the whole
        # feature: LangGraph applies non-None input as a fresh update to the
        # thread's channels on top of whatever the checkpoint holds, so every
        # already-completed node re-ran anyway (verified empirically -- a toy
        # 2-node graph crashed at node b, and a second invoke() with a full
        # fresh input re-ran node a too, identical to no checkpoint existing
        # at all). Passing None is what tells LangGraph "there is no new
        # input, continue this thread from its last checkpoint" -- confirmed
        # against the same toy graph: node a is skipped and only node b (the
        # one that actually failed) executes.
        graph_input = init_agent_state
        if self.config.get("checkpoint_enabled"):
            tid = thread_id(company_name, str(trade_date))
            args.setdefault("config", {}).setdefault("configurable", {})["thread_id"] = tid
            resuming = (
                checkpoint_step(self.config["data_cache_dir"], company_name, str(trade_date))
                is not None
            )
            if resuming:
                graph_input = None

        if self.debug:
            trace = []
            for chunk in self.graph.stream(graph_input, **args):
                if len(chunk["messages"]) == 0:
                    pass
                else:
                    chunk["messages"][-1].pretty_print()
                    trace.append(chunk)
            # Streamed chunks are per-node deltas. Merge them so the returned
            # state matches what graph.invoke() yields in the non-debug path.
            final_state = {}
            for chunk in trace:
                final_state.update(chunk)
        else:
            final_state = self.graph.invoke(graph_input, **args)

        # Store current state for reflection.
        self.curr_state = final_state

        # Log state to disk.
        self._log_state(trade_date, final_state)

        # Store decision for deferred reflection on the next same-ticker run.
        self.memory_log.store_decision(
            ticker=company_name,
            trade_date=trade_date,
            final_trade_decision=final_state["final_trade_decision"],
        )

        # Clear checkpoint on successful completion to avoid stale state.
        if self.config.get("checkpoint_enabled"):
            clear_checkpoint(
                self.config["data_cache_dir"], company_name, str(trade_date)
            )

        return final_state, self.process_signal(final_state["final_trade_decision"])

    def _log_state(self, trade_date, final_state):
        """Log the final state to a JSON file."""
        self.log_states_dict[str(trade_date)] = {
            "company_of_interest": final_state["company_of_interest"],
            "trade_date": final_state["trade_date"],
            "market_report": final_state["market_report"],
            "sentiment_report": final_state["sentiment_report"],
            "news_report": final_state["news_report"],
            "fundamentals_report": final_state["fundamentals_report"],
            "investment_debate_state": {
                "bull_history": final_state["investment_debate_state"]["bull_history"],
                "bear_history": final_state["investment_debate_state"]["bear_history"],
                "history": final_state["investment_debate_state"]["history"],
                "current_response": final_state["investment_debate_state"][
                    "current_response"
                ],
                "judge_decision": final_state["investment_debate_state"][
                    "judge_decision"
                ],
            },
            "trader_investment_decision": final_state["trader_investment_plan"],
            "risk_debate_state": {
                "aggressive_history": final_state["risk_debate_state"]["aggressive_history"],
                "conservative_history": final_state["risk_debate_state"]["conservative_history"],
                "neutral_history": final_state["risk_debate_state"]["neutral_history"],
                "history": final_state["risk_debate_state"]["history"],
                "judge_decision": final_state["risk_debate_state"]["judge_decision"],
            },
            "investment_plan": final_state["investment_plan"],
            "final_trade_decision": final_state["final_trade_decision"],
        }

        # Save to file. Reject ticker values that would escape the
        # results directory when joined as a path component.
        safe_ticker = safe_ticker_component(self.ticker)
        directory = Path(self.config["results_dir"]) / safe_ticker / "TradingAgentsStrategy_logs"
        directory.mkdir(parents=True, exist_ok=True)

        log_path = directory / f"full_states_log_{trade_date}.json"
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(self.log_states_dict[str(trade_date)], f, indent=4)

    def process_signal(self, full_signal):
        """Process a signal to extract the core decision."""
        return self.signal_processor.process_signal(full_signal)
