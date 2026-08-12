"""Parallel analyst execution.

The four analysts are genuinely independent — each needs only the ticker and
date, none reads another's report — but they used to run in a strict chain
because setup.py never read the ``analyst_concurrency_limit`` that config
threaded all the way down to it.

Making them concurrent required more than rewiring: all four shared the one
inherited ``messages`` channel, and every ReAct routing decision reads
``messages[-1]``. In a parallel superstep the four outputs merge in
nondeterministic order, so should_continue_news could read the MARKET
analyst's tool-call message and route the news branch into tools_news.
Per-analyst channels (AgentState) are what make the fan-out correct, and
audit_tool_calls needed a real reducer or concurrent appends raise
InvalidUpdateError.
"""

import threading
import time

import pytest
from langchain_core.messages import AIMessage

# NB: not "setup_module" — pytest treats a module-level name of that
# form as an xunit setup hook and tries to call it.
import tradingagents.graph.setup as graph_setup_mod
from tradingagents.graph.conditional_logic import ConditionalLogic
from tradingagents.graph.setup import GraphSetup

ANALYSTS = ["market", "social", "news", "fundamentals"]
CHANNEL = {
    "market": "market_messages",
    "social": "sentiment_messages",
    "news": "news_messages",
    "fundamentals": "fundamentals_messages",
}
REPORT = {
    "market": "market_report",
    "social": "sentiment_report",
    "news": "news_report",
    "fundamentals": "fundamentals_report",
}


class ConcurrencyProbe:
    """Records the maximum number of analyst nodes running simultaneously."""

    def __init__(self, delay=0.25):
        self.delay = delay
        self.active = 0
        self.peak = 0
        self._lock = threading.Lock()

    def analyst(self, key):
        def node(state):
            with self._lock:
                self.active += 1
                self.peak = max(self.peak, self.active)
            time.sleep(self.delay)  # stand in for LLM latency
            with self._lock:
                self.active -= 1
            return {
                REPORT[key]: f"{key} report",
                CHANNEL[key]: [AIMessage(content="done")],
                # Every analyst appends here at once under parallelism; this
                # only works because audit_tool_calls has an operator.add
                # reducer. Without it LangGraph raises InvalidUpdateError.
                "audit_tool_calls": [{"name": key, "args": {}, "result": "x"}],
            }

        return node


def _stub_downstream(monkeypatch):
    """Stub the debate/risk agents so the graph terminates immediately.

    These stubs must ADVANCE the debate counters, not just return {}. The
    routing functions read ``count`` to decide when to stop; a stub returning
    an empty dict leaves count at 0 forever, so should_continue_debate keeps
    replying "Bull Researcher" — a destination absent from that branch's own
    ends map — and LangGraph raises KeyError. That is a property of the test
    harness, not of analyst parallelism, which is what this file is about.
    """
    def debate_done(state):
        return {"investment_debate_state": {
            "count": 99, "current_response": "Bull", "history": "",
            "bull_history": "", "bear_history": "", "judge_decision": "",
        }}

    def risk_done(state):
        return {"risk_debate_state": {
            "count": 99, "latest_speaker": "Aggressive", "history": "",
            "aggressive_history": "", "conservative_history": "", "neutral_history": "",
            "current_aggressive_response": "", "current_conservative_response": "",
            "current_neutral_response": "", "judge_decision": "",
        }}

    for name in ["create_bull_researcher", "create_bear_researcher"]:
        monkeypatch.setattr(graph_setup_mod, name, lambda llm: debate_done)
    for name in ["create_aggressive_debator", "create_neutral_debator",
                 "create_conservative_debator"]:
        monkeypatch.setattr(graph_setup_mod, name, lambda llm: risk_done)
    for name in ["create_research_manager", "create_trader", "create_portfolio_manager"]:
        monkeypatch.setattr(graph_setup_mod, name, lambda llm: (lambda state: {}))


def _build(probe, limit, monkeypatch):
    for key in ANALYSTS:
        factory_name = {
            "market": "create_market_analyst",
            "social": "create_sentiment_analyst",
            "news": "create_news_analyst",
            "fundamentals": "create_fundamentals_analyst",
        }[key]
        monkeypatch.setattr(
            graph_setup_mod, factory_name, lambda llm, _k=key: probe.analyst(_k)
        )
    _stub_downstream(monkeypatch)

    tool_nodes = {k: (lambda state: {}) for k in ANALYSTS}
    setup = GraphSetup(
        None, None, tool_nodes, ConditionalLogic(1, 1), analyst_concurrency_limit=limit
    )
    return setup.setup_graph(ANALYSTS).compile()


def _initial_state():
    seed = [("human", "X")]
    return {
        "messages": list(seed),
        "market_messages": list(seed),
        "sentiment_messages": list(seed),
        "news_messages": list(seed),
        "fundamentals_messages": list(seed),
        "company_of_interest": "X",
        "trade_date": "2026-08-11",
        "asset_type": "stock",
        "instrument_context": "X",
        "audit_tool_calls": [],
        "investment_debate_state": {"count": 0, "current_response": "", "history": ""},
        "risk_debate_state": {"count": 0, "latest_speaker": "", "history": ""},
        "trader_investment_plan": "",
        "past_context": "",
    }


@pytest.mark.unit
def test_concurrency_limit_1_keeps_analysts_sequential(monkeypatch):
    probe = ConcurrencyProbe()
    graph = _build(probe, 1, monkeypatch)

    graph.invoke(_initial_state(), {"recursion_limit": 60})

    assert probe.peak == 1, "default config must preserve the original sequential chain"


@pytest.mark.unit
def test_concurrency_limit_above_1_runs_analysts_together(monkeypatch):
    probe = ConcurrencyProbe()
    graph = _build(probe, 4, monkeypatch)

    graph.invoke(_initial_state(), {"recursion_limit": 60})

    assert probe.peak > 1, (
        "analysts did not overlap — setup.py is still building a sequential chain"
    )


@pytest.mark.unit
def test_parallel_run_still_produces_every_report(monkeypatch):
    # The join before Bull Researcher must be a real barrier: if the debate
    # started before all four branches finished, some report would be missing.
    probe = ConcurrencyProbe()
    graph = _build(probe, 4, monkeypatch)

    out = graph.invoke(_initial_state(), {"recursion_limit": 60})

    for key in ANALYSTS:
        assert out.get(REPORT[key]), f"{REPORT[key]} missing after parallel run"


@pytest.mark.unit
def test_parallel_run_collects_every_audit_entry(monkeypatch):
    # Concurrent appends to audit_tool_calls are exactly what the
    # operator.add reducer exists for; without it this raises
    # InvalidUpdateError instead of accumulating.
    probe = ConcurrencyProbe()
    graph = _build(probe, 4, monkeypatch)

    out = graph.invoke(_initial_state(), {"recursion_limit": 60})

    names = {entry["name"] for entry in out["audit_tool_calls"]}
    assert names == set(ANALYSTS)


@pytest.mark.unit
def test_parallel_is_faster_than_sequential(monkeypatch):
    delay = 0.3
    seq_probe = ConcurrencyProbe(delay=delay)
    seq_graph = _build(seq_probe, 1, monkeypatch)
    t0 = time.time()
    seq_graph.invoke(_initial_state(), {"recursion_limit": 60})
    sequential = time.time() - t0

    par_probe = ConcurrencyProbe(delay=delay)
    par_graph = _build(par_probe, 4, monkeypatch)
    t0 = time.time()
    par_graph.invoke(_initial_state(), {"recursion_limit": 60})
    parallel = time.time() - t0

    # 4 analysts x delay sequentially vs ~1 x delay in parallel. A loose
    # bound (not 4x) keeps this from flaking on a loaded CI machine while
    # still failing outright if parallelism regresses to sequential.
    assert parallel < sequential * 0.75, (
        f"parallel={parallel:.2f}s not meaningfully faster than sequential={sequential:.2f}s"
    )


@pytest.mark.unit
def test_each_analyst_reads_only_its_own_channel(monkeypatch):
    # The correctness core: an analyst must never see another's messages,
    # or ReAct routing reads the wrong last message under parallelism.
    seen = {}

    def recording_analyst(key):
        def node(state):
            seen[key] = [
                m.content for m in state[CHANNEL[key]] if hasattr(m, "content")
            ]
            return {
                REPORT[key]: "r",
                CHANNEL[key]: [AIMessage(content=f"{key}-only")],
            }
        return node

    for key in ANALYSTS:
        factory_name = {
            "market": "create_market_analyst",
            "social": "create_sentiment_analyst",
            "news": "create_news_analyst",
            "fundamentals": "create_fundamentals_analyst",
        }[key]
        monkeypatch.setattr(
            graph_setup_mod, factory_name, lambda llm, _k=key: recording_analyst(_k)
        )
    _stub_downstream(monkeypatch)

    setup = GraphSetup(
        None, None, {k: (lambda state: {}) for k in ANALYSTS},
        ConditionalLogic(1, 1), analyst_concurrency_limit=4,
    )
    graph = setup.setup_graph(ANALYSTS).compile()
    out = graph.invoke(_initial_state(), {"recursion_limit": 60})

    # No analyst's own channel should contain another analyst's marker.
    for key in ANALYSTS:
        contents = [m.content for m in out[CHANNEL[key]] if hasattr(m, "content")]
        foreign = [
            c for c in contents
            if c.endswith("-only") and not c.startswith(key)
        ]
        assert not foreign, f"{CHANNEL[key]} leaked another analyst's messages: {foreign}"


@pytest.mark.unit
def test_staggered_analyst_completion_does_not_double_trigger_the_debate(monkeypatch):
    """Analysts finishing in DIFFERENT supersteps must still join exactly once.

    Regression test for a live InvalidUpdateError ("At key
    'investment_debate_state': Can receive only one value per step"). The
    original fan-in used one add_edge(clear, "Bull Researcher") per analyst,
    which makes each analyst independently TRIGGER the debate rather than
    acting as a barrier. Every earlier test in this file passed because its
    stub analysts all completed in the SAME superstep — real market and
    fundamentals analysts run extra ReAct rounds for tool calls, finish
    later, and re-triggered Bull Researcher while the bull/bear loop was
    already running. Here each analyst takes a different number of rounds.
    """
    from langchain_core.messages import ToolMessage

    rounds = {"market": 3, "social": 1, "news": 1, "fundamentals": 2}
    calls = {k: 0 for k in ANALYSTS}
    debate_runs = []

    def staggered(key):
        def node(state):
            calls[key] += 1
            if calls[key] < rounds[key]:
                return {CHANNEL[key]: [AIMessage(
                    content="",
                    tool_calls=[{"name": "noop", "args": {}, "id": f"{key}-{calls[key]}"}],
                )]}
            return {REPORT[key]: f"{key} report",
                    CHANNEL[key]: [AIMessage(content="done")]}
        return node

    def tool_stub(key):
        def node(state):
            last = state[CHANNEL[key]][-1]
            tc = (getattr(last, "tool_calls", None) or [{}])[0]
            return {CHANNEL[key]: [ToolMessage(
                content="ok", name="noop", tool_call_id=tc.get("id", "x"))]}
        return node

    for key in ANALYSTS:
        factory_name = {
            "market": "create_market_analyst",
            "social": "create_sentiment_analyst",
            "news": "create_news_analyst",
            "fundamentals": "create_fundamentals_analyst",
        }[key]
        monkeypatch.setattr(graph_setup_mod, factory_name,
                            lambda llm, _k=key: staggered(_k))

    def counting_debate(state):
        debate_runs.append(1)
        return {"investment_debate_state": {
            "count": 99, "current_response": "Bull", "history": "",
            "bull_history": "", "bear_history": "", "judge_decision": "",
        }}

    monkeypatch.setattr(graph_setup_mod, "create_bull_researcher", lambda llm: counting_debate)
    monkeypatch.setattr(graph_setup_mod, "create_bear_researcher", lambda llm: counting_debate)
    for name in ["create_aggressive_debator", "create_neutral_debator",
                 "create_conservative_debator"]:
        monkeypatch.setattr(graph_setup_mod, name, lambda llm: (lambda state: {
            "risk_debate_state": {
                "count": 99, "latest_speaker": "Aggressive", "history": "",
                "aggressive_history": "", "conservative_history": "", "neutral_history": "",
                "current_aggressive_response": "", "current_conservative_response": "",
                "current_neutral_response": "", "judge_decision": "",
            }}))
    for name in ["create_research_manager", "create_trader", "create_portfolio_manager"]:
        monkeypatch.setattr(graph_setup_mod, name, lambda llm: (lambda state: {}))

    setup = GraphSetup(None, None, {k: tool_stub(k) for k in ANALYSTS},
                       ConditionalLogic(1, 1), analyst_concurrency_limit=4)
    graph = setup.setup_graph(ANALYSTS).compile()

    out = graph.invoke(_initial_state(), {"recursion_limit": 80})

    for key in ANALYSTS:
        assert out.get(REPORT[key]), f"{REPORT[key]} missing"
        assert calls[key] == rounds[key], f"{key} ran {calls[key]} rounds, expected {rounds[key]}"
    assert len(debate_runs) == 1, (
        f"debate node ran {len(debate_runs)} times - the analyst fan-in is "
        "re-triggering it instead of acting as a single barrier"
    )
