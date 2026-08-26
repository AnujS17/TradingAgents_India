"""Regression tests for alarming-but-meaningless log output.

A run of BLUEJET on 2026-08-11 completed correctly and produced a good report,
but printed ~45 lines of scary-looking failure text: a yfinance 404, then 42
Reddit JSON decode errors. None of it indicated a real problem, which is worse
than useless — noise that always fires trains you to ignore the log, so the one
line that matters gets skipped too.
"""

import logging
from unittest.mock import MagicMock, patch

import pytest

from tradingagents.agents.utils.agent_utils import _muted_logger, resolve_ticker_symbol
from tradingagents.dataflows.reddit import _json_payload_or_none, fetch_reddit_posts


# --- yfinance probe noise ---------------------------------------------------


@pytest.mark.unit
def test_muted_logger_restores_previous_level():
    log = logging.getLogger("test_mute_target")
    log.setLevel(logging.INFO)

    with _muted_logger("test_mute_target"):
        assert log.level == logging.CRITICAL

    assert log.level == logging.INFO


@pytest.mark.unit
def test_muted_logger_restores_level_even_on_exception():
    # A leaked mute would permanently hide real yfinance errors.
    log = logging.getLogger("test_mute_target_2")
    log.setLevel(logging.WARNING)

    with pytest.raises(RuntimeError):
        with _muted_logger("test_mute_target_2"):
            raise RuntimeError("boom")

    assert log.level == logging.WARNING


@pytest.mark.unit
def test_ticker_resolution_mutes_yfinance_while_probing():
    # resolve_ticker_symbol asks Yahoo "does BLUEJET exist? BLUEJET.NS?" and
    # stops at the first hit; yfinance logs each miss itself, so a successful
    # resolution printed a 404 for the bare symbol at the top of every run.
    resolve_ticker_symbol.cache_clear()
    levels_seen = []

    class FakeHistory:
        def __init__(self, has_rows):
            self.empty = not has_rows

    class FakeTicker:
        def __init__(self, symbol):
            levels_seen.append(logging.getLogger("yfinance").level)
            self._symbol = symbol

        @property
        def info(self):
            return {"previousClose": 100.0} if self._symbol.endswith(".NS") else {}

        def history(self, period=None):
            return FakeHistory(has_rows=self._symbol.endswith(".NS"))

    with patch("tradingagents.agents.utils.agent_utils.yf.Ticker", FakeTicker):
        assert resolve_ticker_symbol("BLUEJET", "stock") == "BLUEJET.NS"

    assert levels_seen and all(level == logging.CRITICAL for level in levels_seen)
    assert logging.getLogger("yfinance").level != logging.CRITICAL
    resolve_ticker_symbol.cache_clear()


# --- Reddit anonymous-access noise -----------------------------------------


def _response(status=200, content_type="text/html", text="\n    <!DOCTYPE html>"):
    r = MagicMock()
    r.status_code = status
    r.headers = {"Content-Type": content_type}
    r.text = text
    r.json.side_effect = ValueError("Expecting value: line 2 column 5 (char 5)")
    r.raise_for_status.return_value = None
    return r


@pytest.mark.unit
def test_html_body_with_http_200_is_detected_as_blocked():
    # old.reddit.com answers 200 with HTML. The status check passes,
    # raise_for_status passes, and .json() then fails at "line 2 column 5" —
    # which is just the '<' of '<!DOCTYPE html>'. Detect the HTML directly so
    # it reads as "blocked", not as a parsing bug.
    assert _json_payload_or_none(_response(status=200)) is None


@pytest.mark.unit
def test_403_html_body_is_detected_as_blocked():
    assert _json_payload_or_none(_response(status=403)) is None


@pytest.mark.unit
def test_genuine_json_response_is_parsed():
    r = MagicMock()
    r.status_code = 200
    r.headers = {"Content-Type": "application/json; charset=UTF-8"}
    r.raise_for_status.return_value = None
    r.json.return_value = {"data": {"children": []}}

    assert _json_payload_or_none(r) == {"data": {"children": []}}


@pytest.mark.unit
def test_praw_zero_results_does_not_trigger_the_dead_json_fallback():
    # The 42 warning lines came from treating a legitimate "no posts" answer
    # as a failure worth retrying over a public API that Reddit now blocks.
    # An authenticated PRAW query that ran is authoritative.
    fake_reddit = MagicMock()
    fake_reddit.subreddit.return_value.search.return_value = []
    fake_reddit.subreddit.return_value.new.return_value = []
    fake_reddit.subreddit.return_value.hot.return_value = []

    with patch("tradingagents.dataflows.reddit._get_reddit_client", return_value=fake_reddit):
        with patch("tradingagents.dataflows.reddit._fetch_subreddit_json") as json_path:
            fetch_reddit_posts(
                "ZZTESTTICKER.NS", subreddits=("IndianStockMarket",), limit_per_sub=5
            )

    json_path.assert_not_called()


@pytest.mark.unit
def test_json_fallback_still_used_when_praw_unavailable():
    # The fallback exists for the no-credentials case; that must keep working.
    with patch(
        "tradingagents.dataflows.reddit._get_reddit_client",
        side_effect=ValueError("Missing REDDIT_CLIENT_ID"),
    ):
        with patch(
            "tradingagents.dataflows.reddit._fetch_subreddit_json", return_value=[]
        ) as json_path:
            fetch_reddit_posts(
                "ZZTESTTICKER2.NS", subreddits=("IndianStockMarket",), limit_per_sub=5
            )

    json_path.assert_called_once()
