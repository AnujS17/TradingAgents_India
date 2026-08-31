"""load_ohlcv's day-keyed cache must not pin a run to stale prices.

The cache file is keyed on (symbol, today) and reused for the rest of the
day, so whatever the vendor had published at the FIRST fetch of that day
became the whole day's truth. KAYNES.NS 2026-08-31: a run at 16:38 IST --
an hour after the 15:30 close -- wrote a cache whose last row was
2026-08-28 because yfinance had not published the 08-31 bar yet. Every
later run reused it, so a 19:51 IST run analysed three-day-old prices and
never saw a -6.5% session (3943 -> 3685). The file was byte-identical to
the previous day's, which is why nothing flagged it.
"""

import os
import time

import pandas as pd
import pytest

from tradingagents.dataflows.stockstats_utils import (
    _STALE_CACHE_RECHECK_SECONDS,
    _cache_covers_date,
)


def _cache(tmp_path, name, last_date, age_seconds=0):
    path = tmp_path / name
    pd.DataFrame(
        {"Date": pd.date_range("2026-08-20", last_date, freq="D"), "Close": 1.0}
    ).to_csv(path, index=False)
    if age_seconds:
        stamp = time.time() - age_seconds
        os.utime(path, (stamp, stamp))
    return str(path)


@pytest.mark.unit
def test_the_real_kaynes_case_forces_a_refetch(tmp_path):
    """The exact shape of the incident: cache ends 08-28, the run asks for
    08-31, and the file was written long enough ago that the vendor has had
    time to publish."""
    path = _cache(tmp_path, "k.csv", "2026-08-28", age_seconds=3600)

    assert _cache_covers_date(path, pd.Timestamp("2026-08-31")) is False


@pytest.mark.unit
def test_a_cache_that_already_reaches_the_date_is_reused(tmp_path):
    """The common case must not lose its cache -- this runs on every call."""
    path = _cache(tmp_path, "k.csv", "2026-08-31")

    assert _cache_covers_date(path, pd.Timestamp("2026-08-31")) is True


@pytest.mark.unit
def test_a_just_written_stale_cache_is_trusted_briefly(tmp_path):
    """Backoff: a holiday, a suspended scrip or a vendor that simply has not
    published yet must not turn every call into a fresh download."""
    path = _cache(tmp_path, "k.csv", "2026-08-28", age_seconds=60)

    assert _cache_covers_date(path, pd.Timestamp("2026-08-31")) is True


@pytest.mark.unit
def test_the_backoff_expires(tmp_path):
    path = _cache(
        tmp_path, "k.csv", "2026-08-28", age_seconds=_STALE_CACHE_RECHECK_SECONDS + 60
    )

    assert _cache_covers_date(path, pd.Timestamp("2026-08-31")) is False


@pytest.mark.unit
@pytest.mark.parametrize("contents", ["", "Date,Close\n", "not,a,csv\n\x00\x01"])
def test_an_unusable_cache_refetches_rather_than_being_trusted(tmp_path, contents):
    """Refetching is always safe; trusting a cache we cannot date-check is
    not. Must never raise -- this sits on the hot path of every fetch."""
    path = tmp_path / "bad.csv"
    path.write_text(contents, encoding="utf-8")

    assert _cache_covers_date(str(path), pd.Timestamp("2026-08-31")) is False


@pytest.mark.unit
def test_a_missing_file_is_reported_as_not_covering(tmp_path):
    assert _cache_covers_date(str(tmp_path / "nope.csv"), pd.Timestamp("2026-08-31")) is False


@pytest.mark.unit
def test_a_timezone_aware_cache_compares_against_a_naive_date(tmp_path):
    """yfinance writes tz-aware timestamps (+05:30 for NSE); comparing those
    against a naive curr_date raises rather than returning a verdict."""
    path = tmp_path / "tz.csv"
    pd.DataFrame(
        {
            "Date": pd.to_datetime(
                ["2026-08-28 00:00:00+05:30", "2026-08-31 00:00:00+05:30"], utc=True
            ),
            "Close": [1.0, 2.0],
        }
    ).to_csv(path, index=False)

    assert _cache_covers_date(str(path), pd.Timestamp("2026-08-31")) is True
