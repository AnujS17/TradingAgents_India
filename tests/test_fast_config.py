"""get_fast_config() — the opt-in fast/platform profile.

A single run through the default pipeline used to be 10+ minutes,
unacceptable for an interactive platform. What the profile is allowed to
trim has narrowed twice, both times because the lever turned out to cost
accuracy rather than just words:

  * 2026-08-12 — article caps, narrowed Reddit scope and a gdelt-stripped
    vendor chain were reverted: input size is not what costs wall-clock.
  * 2026-09-03 — the debate/risk round halving was reverted: 1 round does
    not shorten the debate, it removes the Bull's turn after the Bear.

What is left is genuinely free: run the four independent analysts
concurrently, and ask for a "balanced" (not "concise") write-up.
DEFAULT_CONFIG itself is never mutated.
"""

import pytest

from tradingagents.default_config import DEFAULT_CONFIG, get_fast_config
from tradingagents.graph.conditional_logic import ConditionalLogic


@pytest.mark.unit
def test_fast_config_keeps_the_full_two_round_debate():
    """Restored to 2 on 2026-09-03, matching DEFAULT_CONFIG.

    At 1 round the exchange is Bull -> Bear and stops, so the Bull never
    answers the Bear and an unsupported Bull claim reaches the Research
    Manager unchallenged. ITC.NS 2026-09-02: the Bull asserted "multi-year
    support at 253-255" -- traceable to a StockTwits post, and false (the
    stock had not traded there since 2022) -- and that claim carried a
    Buy-the-dip Overweight. The same ticker at 2 rounds gave the Bull a
    second turn in which it had to engage the Bear directly, conceded the
    honest version ("the lowest print in the 13-month dataset"), and the
    run landed on Underweight with reachable levels.

    Debate depth is no longer the wall-clock lever it was: the analyst
    phase runs concurrently and the provider switch cut per-call latency
    roughly 9x. See QUALITY_BASELINE_ITC.md."""
    fast = get_fast_config()

    assert fast["max_debate_rounds"] == 2
    assert fast["max_risk_discuss_rounds"] == 2
    assert fast["max_debate_rounds"] == DEFAULT_CONFIG["max_debate_rounds"]
    assert fast["max_risk_discuss_rounds"] == DEFAULT_CONFIG["max_risk_discuss_rounds"]


@pytest.mark.unit
def test_two_rounds_give_the_bull_a_turn_after_the_bear():
    """The property the round restoration was actually bought for: the Bull
    must get to answer the Bear, which is where unsupported claims get
    withdrawn."""
    fast = get_fast_config()
    cl = ConditionalLogic(
        max_debate_rounds=fast["max_debate_rounds"],
        max_risk_discuss_rounds=fast["max_risk_discuss_rounds"],
    )
    state = {"investment_debate_state": {"count": 0, "current_response": ""}}

    speakers = []
    for _ in range(8):
        nxt = cl.should_continue_debate(state)
        if nxt == "Research Manager":
            break
        speakers.append(nxt)
        state["investment_debate_state"]["count"] += 1
        state["investment_debate_state"]["current_response"] = nxt.split()[0]

    assert speakers == [
        "Bull Researcher", "Bear Researcher",
        "Bull Researcher", "Bear Researcher",
    ]


@pytest.mark.unit
def test_a_single_round_debate_is_still_a_full_exchange_not_a_dropped_side():
    """Independent of the profile: whenever someone DOES set 1 round (the
    TRADINGAGENTS_MAX_DEBATE_ROUNDS escape hatch), it must still mean Bull
    argues AND Bear rebuts -- not one side skipped entirely, which would
    degrade the debate rather than merely shorten it."""
    cl = ConditionalLogic(max_debate_rounds=1, max_risk_discuss_rounds=1)
    state = {"investment_debate_state": {"count": 0, "current_response": ""}}

    speakers = []
    for _ in range(6):
        nxt = cl.should_continue_debate(state)
        if nxt == "Research Manager":
            break
        speakers.append(nxt)
        state["investment_debate_state"]["count"] += 1
        state["investment_debate_state"]["current_response"] = nxt.split()[0]

    assert speakers == ["Bull Researcher", "Bear Researcher"]


@pytest.mark.unit
def test_a_single_round_risk_debate_still_gives_all_three_analysts_a_turn():
    """Same escape-hatch guarantee as above, for the 3-way risk debate."""
    cl = ConditionalLogic(max_debate_rounds=1, max_risk_discuss_rounds=1)
    state = {"risk_debate_state": {"count": 0, "latest_speaker": ""}}

    speakers = []
    for _ in range(8):
        nxt = cl.should_continue_risk_analysis(state)
        if nxt == "Portfolio Manager":
            break
        speakers.append(nxt)
        state["risk_debate_state"]["count"] += 1
        state["risk_debate_state"]["latest_speaker"] = nxt.split()[0]

    assert speakers == ["Aggressive Analyst", "Conservative Analyst", "Neutral Analyst"]


@pytest.mark.unit
def test_fast_config_does_not_reduce_any_fetched_data():
    """The invariant: fast mode changes output length and scheduling, never
    how much data the model sees.

    Article caps, a narrowed reddit_subreddits list and a gdelt-stripped
    vendor chain all used to live in this profile. They were reverted on
    2026-08-12: input size is not what costs wall-clock (output generation
    is), so they bought little speed while making fast and detailed runs
    incomparable on quality. This test is what stops them coming back
    unnoticed.
    """
    fast = get_fast_config()

    for key in (
        "news_article_limit",
        "global_news_article_limit",
        "india_news_article_limit",
        "global_india_news_article_limit",
        "company_news_lookback_days",
        "reddit_subreddits",
        "data_vendors",
        "tool_vendors",
    ):
        assert fast[key] == DEFAULT_CONFIG[key], f"fast mode must not change {key}"

    # This test's point is that FAST must not narrow the vendor chain
    # relative to DEFAULT -- not that any particular vendor is in it. The
    # equality assertion above already carries that.
    #
    # It used to additionally pin gdelt into the chain, because dropping a
    # fallback is invisible until a primary fails. gdelt was removed from
    # DEFAULT_CONFIG on 2026-09-05 for constant HTTP 429s (see the vendor
    # comment there for the measurements), so pinning it here would now
    # assert the opposite of the intended configuration. The property that
    # actually matters survives as: fast uses whatever DEFAULT uses.
    assert fast["data_vendors"]["news_data"] == DEFAULT_CONFIG["data_vendors"]["news_data"]
    # google_news is the primary company-news search and the one vendor the
    # chain cannot degrade gracefully without.
    assert "google_news" in fast["data_vendors"]["news_data"]


@pytest.mark.unit
def test_fast_config_only_changes_output_and_scheduling_keys():
    """Whitelist, so a new input-reducing key cannot be added silently."""
    fast = get_fast_config()
    changed = {k for k in DEFAULT_CONFIG if fast[k] != DEFAULT_CONFIG[k]}

    # report_style and max_output_tokens were removed on 2026-08-12: for an
    # LLM, output length IS reasoning depth, so shortening the write-up made
    # fast runs reason less rather than merely write less.
    #
    # max_debate_rounds / max_risk_discuss_rounds left this set on
    # 2026-09-03 for the same reason, one level up: halving the rounds does
    # not shorten the debate, it removes the Bull's chance to answer the
    # Bear. Concurrency -- genuinely free, since the four analysts are
    # independent -- is the only real scheduling lever left.
    assert changed == {
        "analyst_concurrency_limit",
        "report_style",
    }
    # "balanced", never "concise" — concise is what dropped the demerger
    # filing and miscredited a separately-listed company's profit.
    assert get_fast_config()["report_style"] == "balanced"


@pytest.mark.unit
def test_fast_config_does_not_mutate_default_config():
    # get_fast_config must deep-copy: a shallow copy would let editing
    # fast["data_vendors"] silently corrupt DEFAULT_CONFIG's dict too, since
    # nested dicts are shared references under a shallow copy/spread.
    before = {
        "data_vendors": dict(DEFAULT_CONFIG["data_vendors"]),
        "tool_vendors": dict(DEFAULT_CONFIG["tool_vendors"]),
    }

    get_fast_config()

    assert DEFAULT_CONFIG["data_vendors"] == before["data_vendors"]
    assert DEFAULT_CONFIG["tool_vendors"] == before["tool_vendors"]
    assert DEFAULT_CONFIG["max_debate_rounds"] == 2
    assert DEFAULT_CONFIG["report_style"] == "detailed"


@pytest.mark.unit
def test_fast_config_preserves_sibling_keys_in_nested_dicts():
    # A shallow top-level override ({"data_vendors": {"news_data": ...}})
    # would silently replace the WHOLE data_vendors dict, deleting
    # core_stock_apis/technical_indicators/fundamental_data and breaking
    # price and fundamentals data entirely — a bug with no connection to the
    # actual goal (dropping gdelt from the news chain specifically).
    fast = get_fast_config()

    assert fast["data_vendors"]["core_stock_apis"] == DEFAULT_CONFIG["data_vendors"]["core_stock_apis"]
    assert fast["data_vendors"]["technical_indicators"] == DEFAULT_CONFIG["data_vendors"]["technical_indicators"]
    assert fast["data_vendors"]["fundamental_data"] == DEFAULT_CONFIG["data_vendors"]["fundamental_data"]


@pytest.mark.unit
def test_fast_config_two_calls_are_independent():
    # Each call must return its own deep copy — mutating one result must not
    # leak into a second call or back into DEFAULT_CONFIG.
    first = get_fast_config()
    first["data_vendors"]["news_data"] = "MUTATED"

    second = get_fast_config()

    assert second["data_vendors"]["news_data"] != "MUTATED"
