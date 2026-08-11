"""NSE corporate-filings fetcher tests.

The authoritative record of scheduled corporate events. In the TMPV.NS run of
2026-08-10 the only signal of an upcoming earnings catalyst was a Reddit user
mentioning "results on 12th August"; NSE's own board-meeting filing says
13-Aug-2026. Every other source in the pipeline reports events second-hand —
this one is the filing itself.
"""

from unittest.mock import MagicMock, patch

import pytest

from tradingagents.dataflows.nse_announcements import (
    clear_cache,
    fetch_corporate_announcements,
)

PAYLOAD = {
    "borad_meeting": {
        "data": [
            {
                "symbol": "TMPV",
                "meetingdate": "13-Aug-2026",
                "purpose": "Board Meeting to consider and approve the Audited Financial results",
            }
        ]
    },
    "latest_announcements": {
        "data": [
            {
                "symbol": "TMPV",
                "broadcastdate": "07-Aug-2026 21:26:50",
                "subject": "Analysts/Institutional Investor Meet Updates",
            }
        ]
    },
    "corporate_actions": {
        "data": [{"symbol": "TMPV", "exdate": "19-Jun-2026", "purpose": "Dividend - Rs 3 Per Share"}]
    },
}


@pytest.fixture(autouse=True)
def _reset():
    clear_cache()
    yield
    clear_cache()


def _session(payload=PAYLOAD, status=200):
    resp = MagicMock()
    resp.json.return_value = payload
    resp.status_code = status
    resp.raise_for_status.return_value = None
    sess = MagicMock()
    sess.get.return_value = resp
    return sess


@pytest.mark.unit
def test_board_meeting_date_is_surfaced():
    with patch("tradingagents.dataflows.nse_announcements.requests.Session", return_value=_session()):
        out = fetch_corporate_announcements("TMPV.NS", "2026-08-11")

    assert "13-Aug-2026" in out
    assert "Audited Financial results" in out


@pytest.mark.unit
def test_all_three_sections_render():
    with patch("tradingagents.dataflows.nse_announcements.requests.Session", return_value=_session()):
        out = fetch_corporate_announcements("TMPV.NS", "2026-08-11")

    assert "Board Meetings" in out
    assert "Exchange Announcements" in out
    assert "Corporate Actions" in out
    assert "Dividend - Rs 3 Per Share" in out


@pytest.mark.unit
def test_output_states_filings_outrank_inferred_dates():
    # The whole point of adding this source: a Reddit-inferred date was a day
    # wrong. The prompt block must say which source wins.
    with patch("tradingagents.dataflows.nse_announcements.requests.Session", return_value=_session()):
        out = fetch_corporate_announcements("TMPV.NS", "2026-08-11")

    assert "authoritative" in out.lower()


@pytest.mark.unit
def test_exchange_suffix_is_stripped_for_nse_symbol():
    sess = _session()
    with patch("tradingagents.dataflows.nse_announcements.requests.Session", return_value=sess):
        fetch_corporate_announcements("TMPV.NS", "2026-08-11")

    called = " ".join(str(c) for c in sess.get.call_args_list)
    assert "symbol=TMPV&" in called
    assert "TMPV.NS" not in called


@pytest.mark.unit
def test_network_failure_degrades_to_placeholder():
    # NSE blocks aggressively; a blocked NSE must never block a run.
    with patch("tradingagents.dataflows.nse_announcements.requests.Session", side_effect=OSError("blocked")):
        out = fetch_corporate_announcements("TMPV.NS", "2026-08-11")

    assert out.startswith("<NSE corporate announcements unavailable")


@pytest.mark.unit
def test_empty_payload_degrades_to_placeholder():
    with patch("tradingagents.dataflows.nse_announcements.requests.Session", return_value=_session(payload={})):
        out = fetch_corporate_announcements("TMPV.NS", "2026-08-11")

    assert out.startswith("<no NSE corporate announcements found")


@pytest.mark.unit
def test_unexpected_shape_does_not_raise():
    # NSE changes its response shape without notice; _rows must tolerate it.
    odd = {"borad_meeting": [{"meetingdate": "13-Aug-2026", "purpose": "results"}]}
    with patch("tradingagents.dataflows.nse_announcements.requests.Session", return_value=_session(payload=odd)):
        out = fetch_corporate_announcements("TMPV.NS", "2026-08-11")

    assert "13-Aug-2026" in out


@pytest.mark.unit
def test_result_is_cached_per_symbol_and_date():
    sess = _session()
    with patch("tradingagents.dataflows.nse_announcements.requests.Session", return_value=sess) as mock_sess:
        fetch_corporate_announcements("TMPV.NS", "2026-08-11")
        fetch_corporate_announcements("TMPV.NS", "2026-08-11")

    assert mock_sess.call_count == 1


@pytest.mark.unit
def test_different_trade_date_refetches():
    # A re-run on a new trade date must not replay yesterday's filings.
    sess = _session()
    with patch("tradingagents.dataflows.nse_announcements.requests.Session", return_value=sess) as mock_sess:
        fetch_corporate_announcements("TMPV.NS", "2026-08-11")
        fetch_corporate_announcements("TMPV.NS", "2026-08-12")

    assert mock_sess.call_count == 2
