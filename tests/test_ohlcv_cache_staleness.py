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


# --- The unpriced-stub row (ITC.NS 2026-09-02) --------------------------
#
# The date-only freshness check above closed the KAYNES shape but not this
# one. yfinance publishes a partially-consolidated bar for the session in
# progress: a real date and a real volume, with Open/High/Low/Close all
# NaN. The cache for ITC.NS on 2026-09-02 held exactly that --
#
#     2026-08-31,255.5,266.55,255.5,266.0,24575845
#     2026-09-01,,,,,31232541
#
# -- and a check that reads only Date sees "the vendor has published
# 09-01". It has not published anything usable: get_stock_stats drops the
# row on dropna(subset=["Close"]) a few lines later. The 00:26 IST run
# therefore analysed the 08-31 close of 255.50 while the stock had closed
# at 266.60 on 09-01 (+4.3%), and recommended an entry that was never
# fillable at any point afterwards.
#
# The elapsed-time grace window cannot rescue this: that run's cache was
# 14 minutes old, well inside the window. What distinguishes it is that
# the file itself carries the evidence -- a dated row NEWER than the
# newest priced one is positive proof the vendor is publishing a session
# we hold only as a stub.


def _stub_cache(tmp_path, name="itc.csv", age_seconds=0):
    """A cache ending in a real 08-31 bar plus an unpriced 09-01 stub."""
    path = tmp_path / name
    path.write_text(
        "Date,Close,High,Low,Open,Volume\n"
        "2026-08-28,266.0,269.0,264.8,269.0,15200847\n"
        "2026-08-31,255.5,266.55,255.5,266.0,24575845\n"
        "2026-09-01,,,,,31232541\n",
        encoding="utf-8",
    )
    if age_seconds:
        stamp = time.time() - age_seconds
        os.utime(path, (stamp, stamp))
    return str(path)


@pytest.mark.unit
def test_an_unpriced_newest_row_does_not_count_as_covering_its_date(tmp_path):
    """The stub row's own date must not satisfy a request for that date."""
    path = _stub_cache(tmp_path)

    assert _cache_covers_date(path, pd.Timestamp("2026-09-01")) is False


@pytest.mark.unit
def test_the_real_itc_case_refetches_even_inside_the_grace_window(tmp_path):
    """The exact incident: a 14-minute-old cache, comfortably inside the
    recheck window, whose newest priced row is a full session behind a
    stub row it already holds. The window must not protect it."""
    path = _stub_cache(tmp_path, age_seconds=14 * 60)
    assert 14 * 60 < _STALE_CACHE_RECHECK_SECONDS  # the window really is open

    assert _cache_covers_date(path, pd.Timestamp("2026-09-02")) is False


@pytest.mark.unit
def test_a_fully_priced_cache_still_gets_its_grace_window(tmp_path):
    """No stub row means no evidence the vendor has anything newer, so a
    fresh file is still trusted -- otherwise every call refetches."""
    path = _cache(tmp_path, "ok.csv", "2026-08-31", age_seconds=60)

    assert _cache_covers_date(path, pd.Timestamp("2026-09-02")) is True


@pytest.mark.unit
def test_the_recheck_window_is_configurable(tmp_path):
    """ohlcv_cache_recheck_seconds must actually move the boundary."""
    from tradingagents.dataflows.config import get_config, set_config

    path = _cache(tmp_path, "ok.csv", "2026-08-31", age_seconds=40 * 60)
    original = get_config()
    try:
        widened = dict(original)
        widened["ohlcv_cache_recheck_seconds"] = 60 * 60
        set_config(widened)
        assert _cache_covers_date(path, pd.Timestamp("2026-09-02")) is True

        narrowed = dict(original)
        narrowed["ohlcv_cache_recheck_seconds"] = 10 * 60
        set_config(narrowed)
        assert _cache_covers_date(path, pd.Timestamp("2026-09-02")) is False
    finally:
        set_config(original)


def _seed_cache_where_load_ohlcv_looks(tmp_path, symbol="ITC.NS"):
    """Write a stub cache under the exact (symbol, today) name load_ohlcv
    derives, so the real function finds it."""
    today = pd.Timestamp.today()
    name = (
        f"{symbol}-YFin-data-"
        f"{(today - pd.DateOffset(years=5)).strftime('%Y-%m-%d')}-"
        f"{today.strftime('%Y-%m-%d')}.csv"
    )
    return _stub_cache(tmp_path, name=name, age_seconds=48 * 3600)


@pytest.mark.unit
@pytest.mark.parametrize(
    "freshness_on, expect_download",
    [(True, True), (False, False)],
    ids=["on-refetches", "off-serves-the-stale-file"],
)
def test_the_freshness_check_toggle_decides_whether_a_stale_cache_is_refetched(
    tmp_path, monkeypatch, freshness_on, expect_download
):
    """Drives the real load_ohlcv against a 48-hour-old stub cache and
    asserts on whether the vendor was actually called -- the toggle is
    only meaningful if it changes that."""
    from tradingagents.dataflows import stockstats_utils as su
    from tradingagents.dataflows.config import get_config, set_config

    _seed_cache_where_load_ohlcv_looks(tmp_path)
    downloaded = {"called": False}

    def _fake_download(*args, **kwargs):
        downloaded["called"] = True
        frame = pd.DataFrame(
            {"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [1.0], "Volume": [1]},
            index=pd.DatetimeIndex([pd.Timestamp("2026-09-02")], name="Date"),
        )
        return frame

    monkeypatch.setattr(su.yf, "download", _fake_download)

    original = get_config()
    try:
        cfg = dict(original)
        cfg["data_cache_dir"] = str(tmp_path)
        cfg["ohlcv_cache_freshness_check"] = freshness_on
        set_config(cfg)

        su.load_ohlcv("ITC.NS", "2026-09-02")
    finally:
        set_config(original)

    assert downloaded["called"] is expect_download
