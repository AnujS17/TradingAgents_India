"""Guards against a stale price bar becoming an authoritative number.

ITC.NS 2026-09-02 is the incident all of these encode. The OHLCV cache held
the 08-31 close of 255.50 while the stock had closed at 266.60 on 09-01
(+4.3%) and 266.30 on 09-02. Two independent things then went wrong, and it
takes both fixes to stop a repeat:

  * The market snapshot's staleness note read as routine weekend handling
    ("the latest prior trading date was used"), so no agent acted on it --
    even though the SAME run's news report led with "ITC Rallies 4.3%"
    dated 09-01.
  * The Trader's price anchor told the model its entry "must be a level
    that makes sense against THIS price", which is correct guidance
    attached to a wrong number. It proposed an entry at 255.50 that was
    never fillable again.

The BASE system, which has no anchor at all, read the same stale snapshot
and still produced reachable levels (270, into the analysts' 268-272
shelf). That is the bar these tests hold the modified engine to.
"""

import pandas as pd
import pytest
from unittest.mock import patch

import tradingagents.agents.trader.trader as trader_mod
import tradingagents.dataflows.market_data_validator as mv
import tradingagents.dataflows.stockstats_utils as su
from tradingagents.agents.trader.trader import _sessions_missed


# --- _sessions_missed: weekday arithmetic, not calendar -------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "as_of, trade_date, expected, why",
    [
        ("2026-08-31", "2026-09-02", 1, "THE ITC CASE: Mon bar, Wed run, Tue missed"),
        ("2026-08-28", "2026-08-31", 0, "Fri bar read Mon: 3 calendar days, 0 missed"),
        ("2026-09-01", "2026-09-02", 0, "consecutive sessions are current"),
        ("2026-08-31", "2026-08-31", 0, "same day"),
        ("2026-08-28", "2026-09-02", 2, "Fri bar, Wed run: Mon and Tue missed"),
        ("not-a-date", "2026-09-02", 0, "undateable anchor is not a stale anchor"),
    ],
)
def test_sessions_missed_counts_trading_days_not_calendar_days(
    as_of, trade_date, expected, why
):
    assert _sessions_missed(as_of, trade_date) == expected, why


# --- the anchor stops binding once it is behind --------------------------


def _anchor_for(trade_date, last_bar="2026-08-31"):
    df = pd.DataFrame(
        {"Date": [pd.Timestamp("2026-08-28"), pd.Timestamp(last_bar)],
         "Close": [266.0, 255.5]}
    )
    with patch.object(su, "load_ohlcv", return_value=df):
        return trader_mod._price_anchor("ITC.NS", trade_date)


@pytest.mark.unit
def test_a_current_anchor_still_binds_the_trader_to_spot():
    """The anchor's whole reason for existing -- SKYGOLD.NS proposed an
    entry of 5000 on a stock whose 52-week high is 848 -- must survive."""
    anchor = _anchor_for("2026-08-31")

    assert "must be a level that makes sense against THIS price" in anchor
    assert "STALE" not in anchor


@pytest.mark.unit
def test_a_stale_anchor_does_not_bind_and_says_so():
    anchor = _anchor_for("2026-09-02")

    assert "STALE" in anchor
    assert "Do NOT anchor your entry or stop to it" in anchor
    # The binding instruction must be gone, not merely counterbalanced.
    assert "must be a level that makes sense against THIS price" not in anchor


@pytest.mark.unit
def test_a_stale_anchor_still_bounds_the_order_of_magnitude():
    """Degraded, not withdrawn: the SKYGOLD failure class must stay closed
    even when the reference price is a session or two behind."""
    anchor = _anchor_for("2026-09-02")

    assert "255.50" in anchor
    assert "order-of-magnitude" in anchor


@pytest.mark.unit
def test_a_stale_anchor_points_the_trader_at_the_news_reports():
    """The run already contained the correction -- a 09-01 headline naming
    the move. The anchor has to send the model to look at it."""
    anchor = _anchor_for("2026-09-02")

    assert "news" in anchor
    assert "2026-08-31" in anchor


# --- the snapshot warning names the gap ----------------------------------


def _snapshot(last_bar, requested):
    idx = pd.bdate_range("2026-06-01", last_bar)
    df = pd.DataFrame({
        "Date": idx, "Open": 266.0, "High": 266.55,
        "Low": 255.5, "Close": 255.5, "Volume": 24575845,
    })
    with patch.object(mv, "load_ohlcv", return_value=df):
        return mv.build_verified_market_snapshot("ITC.NS", requested)


@pytest.mark.unit
def test_a_missed_session_raises_a_named_staleness_warning():
    out = _snapshot("2026-08-31", "2026-09-02")

    assert "STALENESS WARNING" in out
    assert "1 trading session falls" in out
    # It must tell the reader what to DO, not just that a date differs.
    assert "news or sentiment reports" in out


@pytest.mark.unit
def test_a_weekend_gap_is_not_reported_as_staleness():
    """Fri bar read on Mon misses nothing. A warning here would fire on
    most Monday runs and train every agent to ignore it."""
    out = _snapshot("2026-09-04", "2026-09-07")

    assert "STALENESS WARNING" not in out
    assert "No trading session was missed" in out


@pytest.mark.unit
def test_the_warning_scales_its_wording_past_one_session():
    out = _snapshot("2026-08-28", "2026-09-02")

    assert "2 trading sessions fall" in out
