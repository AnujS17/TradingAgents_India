"""yf_retry's retry_on_empty: backoff on the failure mode that actually
happens, not just on the one yfinance raises for.

yfinance raises YFRateLimitError on an explicit HTTP 429, but
PERF_HANDOFF.md's own finding is that under sustained load its informal API
usually throttles by returning an EMPTY frame instead of raising anything.
PINELABS.NS and LENSKART.NS both lost their verified market snapshot to
this on 2026-08-26/27 ("yfinance returned no data"), and both fetch fine on
retry -- which is what identifies it as throttling rather than a bad
symbol. The 429-only path never engaged for either.

time.sleep is patched throughout so these tests assert the backoff
schedule without paying for it in wall-clock, matching the pattern in
test_gdelt_retry.py.
"""

from unittest.mock import patch

import pandas as pd
import pytest

from tradingagents.dataflows.stockstats_utils import _is_empty_result, yf_retry


@pytest.mark.unit
@pytest.mark.parametrize(
    "value,expected",
    [
        (None, True),
        (pd.DataFrame(), True),
        ([], True),
        ((), True),
        ("", True),
        ({}, True),
        (pd.DataFrame({"Close": [1.0]}), False),
        ([1], False),
        ("x", False),
        (0, False),  # a real, meaningful falsy value -- not "empty"
    ],
)
def test_is_empty_result_covers_every_shape_yfinance_uses(value, expected):
    assert _is_empty_result(value) is expected


@pytest.mark.unit
def test_retry_on_empty_off_by_default_returns_the_empty_result_immediately():
    """Most callers must NOT retry on empty -- a news search with no hits,
    an unfiled statement, a young listing with no history for a window are
    all legitimate empty answers, and retrying them burns the backoff on a
    result that will never change."""
    calls = {"n": 0}

    def always_empty():
        calls["n"] += 1
        return pd.DataFrame()

    with patch("tradingagents.dataflows.stockstats_utils.time.sleep") as sleep:
        result = yf_retry(always_empty)

    assert calls["n"] == 1
    assert result.empty
    sleep.assert_not_called()


@pytest.mark.unit
def test_retry_on_empty_recovers_once_the_vendor_stops_throttling():
    """The exact shape of the incident: empty, empty, then real data --
    modelling a transient throttle that clears on its own."""
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            return pd.DataFrame()
        return pd.DataFrame({"Close": [165.07]})

    with patch("tradingagents.dataflows.stockstats_utils.time.sleep") as sleep:
        result = yf_retry(flaky, base_delay=2.0, retry_on_empty=True)

    assert calls["n"] == 3
    assert not result.empty
    assert (result["Close"] == 165.07).any()
    # Exponential: 2.0 * 2**0, 2.0 * 2**1 -- same schedule the 429 path uses.
    assert [c.args[0] for c in sleep.call_args_list] == [2.0, 4.0]


@pytest.mark.unit
def test_retry_on_empty_gives_up_after_max_retries_and_returns_empty_not_raises():
    """A genuinely-empty answer (a delisted symbol, a real data gap) must
    still come back as an empty result after exhausting retries, not raise
    -- callers already handle an empty frame; a new exception type here
    would break them."""
    calls = {"n": 0}

    def always_empty():
        calls["n"] += 1
        return pd.DataFrame()

    with patch("tradingagents.dataflows.stockstats_utils.time.sleep") as sleep:
        result = yf_retry(always_empty, max_retries=3, base_delay=1.0, retry_on_empty=True)

    assert calls["n"] == 4  # initial attempt + 3 retries
    assert result.empty
    assert sleep.call_count == 3


@pytest.mark.unit
def test_a_rate_limit_error_still_takes_priority_over_the_empty_check():
    """The two retry paths must compose, not conflict: a 429 is retried on
    its own schedule regardless of retry_on_empty, then a subsequent empty
    (non-429) result is retried by the empty-result path."""
    from yfinance.exceptions import YFRateLimitError

    calls = {"n": 0}

    def sequence():
        calls["n"] += 1
        if calls["n"] == 1:
            raise YFRateLimitError()
        return pd.DataFrame()  # empty, but no longer rate-limited

    with patch("tradingagents.dataflows.stockstats_utils.time.sleep"):
        result = yf_retry(sequence, max_retries=3, base_delay=0.5, retry_on_empty=True)

    assert calls["n"] > 1
    assert result.empty


@pytest.mark.unit
def test_retry_on_empty_does_not_change_default_max_retries_behavior():
    """Regression guard: retry_on_empty is additive. With it explicitly
    False (the default used everywhere except load_ohlcv's price fetch),
    behaviour must be byte-identical to before this change existed."""
    calls = {"n": 0}

    def always_empty():
        calls["n"] += 1
        return []

    with patch("tradingagents.dataflows.stockstats_utils.time.sleep") as sleep:
        result = yf_retry(always_empty)

    assert calls["n"] == 1
    assert result == []
    sleep.assert_not_called()
