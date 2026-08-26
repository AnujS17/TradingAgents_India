from unittest.mock import patch

import pytest
import requests

from tradingagents.dataflows.interface import VENDOR_METHODS, route_to_vendor
from tradingagents.graph.trading_graph import TradingAgentsGraph


@pytest.mark.unit
def test_fundamentals_tool_node_accepts_news_context_tools():
    graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    tool_nodes = TradingAgentsGraph._create_tool_nodes(graph)

    tool_names = set(tool_nodes["fundamentals"].tools_by_name)

    assert "get_fundamentals" in tool_names
    assert "get_news" in tool_names
    assert "get_global_news" in tool_names


@pytest.mark.unit
def test_market_tool_node_does_not_expose_verified_snapshot_as_callable_tool():
    # get_verified_market_snapshot is pre-fetched directly in
    # market_analyst.py, not offered to the LLM via bind_tools — it used to
    # be both, which let the LLM redundantly re-invoke it with identical
    # args (observed live: confusing duplicate [Tool Call]/[Data] log
    # entries with no new information, RELIANCE run 2026-08-10).
    #
    # get_indicators is excluded for the same reason as of 2026-08-11: the
    # verified snapshot's Indicator Trend section now covers what a redundant
    # get_indicators call would have returned (see
    # market_data_validator.TREND_INDICATORS).
    graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    tool_nodes = TradingAgentsGraph._create_tool_nodes(graph)

    tool_names = set(tool_nodes["market"].tools_by_name)

    assert "get_stock_data" in tool_names
    assert "get_indicators" not in tool_names
    assert "get_verified_market_snapshot" not in tool_names


@pytest.mark.unit
def test_route_to_vendor_falls_back_on_error_string_result():
    def alpha_error(*args, **kwargs):
        return "Error: No data returned for close_10_ema"

    def yfinance_success(*args, **kwargs):
        return "fallback indicator data"

    vendor_methods = {
        "get_indicators": {
            "alpha_vantage": alpha_error,
            "yfinance": yfinance_success,
        }
    }

    config = {
        "tool_vendors": {"get_indicators": "alpha_vantage"},
        "data_vendors": {"technical_indicators": "alpha_vantage"},
    }

    with patch("tradingagents.dataflows.interface.VENDOR_METHODS", vendor_methods):
        with patch("tradingagents.dataflows.interface.get_config", return_value=config):
            assert (
                route_to_vendor("get_indicators", "NVDA", "close_10_ema", "2026-05-28", 30)
                == "fallback indicator data"
            )


@pytest.mark.unit
def test_news_route_falls_back_on_network_error():
    def alpha_network_error(*args, **kwargs):
        raise requests.exceptions.ProxyError("proxy unavailable")

    def gdelt_success(*args, **kwargs):
        return "fallback global news"

    vendor_methods = {
        "get_global_news": {
            "alpha_vantage": alpha_network_error,
            "gdelt": gdelt_success,
        }
    }

    config = {
        "tool_vendors": {"get_global_news": "alpha_vantage,gdelt"},
        "data_vendors": {"news_data": "alpha_vantage,gdelt"},
    }

    with patch("tradingagents.dataflows.interface.VENDOR_METHODS", vendor_methods):
        with patch("tradingagents.dataflows.interface.get_config", return_value=config):
            assert route_to_vendor("get_global_news", "2026-06-02", None, None) == "fallback global news"


@pytest.mark.unit
def test_news_route_falls_back_on_malformed_json_response():
    # Regression test: requests.exceptions.JSONDecodeError (raised by
    # response.json() on an empty/non-JSON body, e.g. GDELT returning "")
    # is BOTH a requests.exceptions.RequestException AND a ValueError.
    # route_to_vendor used to check `except ValueError` before
    # `except requests.exceptions.RequestException`, so this fell into the
    # "missing API key" branch, didn't match that message pattern, and
    # re-raised — crashing the whole run instead of falling back to the
    # next vendor. Reproduced live against RELIANCE.BO.
    def gdelt_malformed_json(*args, **kwargs):
        raise requests.exceptions.JSONDecodeError("Expecting value", "", 0)

    def yfinance_success(*args, **kwargs):
        return "fallback news"

    vendor_methods = {
        "get_news": {
            "gdelt": gdelt_malformed_json,
            "yfinance": yfinance_success,
        }
    }

    config = {
        "tool_vendors": {"get_news": "gdelt,yfinance"},
        "data_vendors": {"news_data": "gdelt,yfinance"},
    }

    with patch("tradingagents.dataflows.interface.VENDOR_METHODS", vendor_methods):
        with patch("tradingagents.dataflows.interface.get_config", return_value=config):
            assert (
                route_to_vendor("get_news", "RELIANCE.BO", "2026-08-03", "2026-08-10")
                == "fallback news"
            )


def _news_config(vendors, merged):
    return {
        "tool_vendors": {"get_news": vendors},
        "data_vendors": {"news_data": vendors},
        "merged_news_vendors": merged,
    }


@pytest.mark.unit
def test_merged_news_vendors_are_unioned_not_first_wins():
    # route_to_vendor used to return the FIRST vendor that succeeded and stop,
    # so a thin yfinance response (Yahoo caps company news at ~12 articles)
    # became the entire news picture and GDELT was never consulted.
    vendor_methods = {
        "get_news": {
            "gdelt": lambda *a, **k: "gdelt articles",
            "yfinance": lambda *a, **k: "yfinance articles",
        }
    }
    config = _news_config("gdelt,yfinance", ["gdelt", "yfinance"])

    with patch("tradingagents.dataflows.interface.VENDOR_METHODS", vendor_methods):
        with patch("tradingagents.dataflows.interface.get_config", return_value=config):
            result = route_to_vendor("get_news", "LAURUSLABS.BO", "2026-07-11", "2026-08-10")

    assert "gdelt articles" in result
    assert "yfinance articles" in result


@pytest.mark.unit
def test_merge_pass_survives_a_vendor_network_error():
    # Regression guard: the merge pass used to catch only
    # AlphaVantageRateLimitError, so a vendor raising a network error there
    # would have crashed the run instead of degrading to the other vendor —
    # the same class of bug already fixed once in the fallback pass.
    def gdelt_boom(*args, **kwargs):
        raise requests.exceptions.JSONDecodeError("Expecting value", "", 0)

    vendor_methods = {
        "get_news": {
            "gdelt": gdelt_boom,
            "yfinance": lambda *a, **k: "yfinance articles",
        }
    }
    config = _news_config("gdelt,yfinance", ["gdelt", "yfinance"])

    with patch("tradingagents.dataflows.interface.VENDOR_METHODS", vendor_methods):
        with patch("tradingagents.dataflows.interface.get_config", return_value=config):
            result = route_to_vendor("get_news", "LAURUSLABS.BO", "2026-07-11", "2026-08-10")

    assert "yfinance articles" in result
    # Partial coverage must be stated, not silently hidden: a thin result from
    # one surviving vendor previously read to the analyst as "little news
    # exists" rather than "one source was down".
    assert "gdelt" in result
    assert "Coverage note" in result


@pytest.mark.unit
def test_empty_vendor_message_is_not_merged_as_content():
    # Regression: yfinance's "No news found for X between ..." did not match
    # any error prefix, so under merging it was treated as a real payload and
    # concatenated directly beneath 30 genuine Google News articles — the
    # company-news block ended with a flat claim that no news existed
    # (observed live, BLUEJET run 2026-08-11).
    vendor_methods = {
        "get_news": {
            "google_news": lambda *a, **k: "## Real articles\n### Headline",
            "yfinance": lambda *a, **k: "No news found for BLUEJET.NS between 2026-07-12 and 2026-08-11",
        }
    }
    config = _news_config("google_news,yfinance", ["google_news", "yfinance"])

    with patch("tradingagents.dataflows.interface.VENDOR_METHODS", vendor_methods):
        with patch("tradingagents.dataflows.interface.get_config", return_value=config):
            result = route_to_vendor("get_news", "BLUEJET.NS", "2026-07-12", "2026-08-11")

    assert "Real articles" in result
    assert "No news found" not in result
    # An empty vendor counts as not contributing, so coverage must be flagged.
    assert "Coverage note" in result


@pytest.mark.unit
@pytest.mark.parametrize(
    "message",
    [
        "No news found for X between A and B",
        "No Google News found for X between A and B",
        "No GDELT news found for X between A and B",
        "Error fetching get_news from gdelt: boom",
        "<no articles>",
    ],
)
def test_empty_result_messages_are_recognised(message):
    from tradingagents.dataflows.interface import _is_vendor_error_result

    assert _is_vendor_error_result(message)


@pytest.mark.unit
def test_real_content_is_not_mistaken_for_an_empty_result():
    from tradingagents.dataflows.interface import _is_vendor_error_result

    assert not _is_vendor_error_result("## BLUEJET.NS News\n### Q1 results beat estimates")


@pytest.mark.unit
def test_merge_failure_still_falls_through_to_unmerged_vendors():
    vendor_methods = {
        "get_news": {
            "gdelt": lambda *a, **k: "No GDELT news found for X",
            "yfinance": lambda *a, **k: "<no articles>",
            "finnhub": lambda *a, **k: "finnhub articles",
        }
    }
    config = _news_config("gdelt,yfinance,finnhub", ["gdelt", "yfinance"])

    with patch("tradingagents.dataflows.interface.VENDOR_METHODS", vendor_methods):
        with patch("tradingagents.dataflows.interface.get_config", return_value=config):
            result = route_to_vendor("get_news", "X", "2026-07-11", "2026-08-10")

    assert result == "finnhub articles"


@pytest.mark.unit
def test_absent_merge_config_preserves_first_wins_behaviour():
    # Configs written before this setting existed must not silently start
    # making an extra vendor call per fetch.
    calls = []

    def gdelt(*args, **kwargs):
        calls.append("gdelt")
        return "gdelt articles"

    def yfinance(*args, **kwargs):
        calls.append("yfinance")
        return "yfinance articles"

    vendor_methods = {"get_news": {"gdelt": gdelt, "yfinance": yfinance}}
    config = {
        "tool_vendors": {"get_news": "gdelt,yfinance"},
        "data_vendors": {"news_data": "gdelt,yfinance"},
    }

    with patch("tradingagents.dataflows.interface.VENDOR_METHODS", vendor_methods):
        with patch("tradingagents.dataflows.interface.get_config", return_value=config):
            result = route_to_vendor("get_news", "X", "2026-07-11", "2026-08-10")

    assert result == "gdelt articles"
    assert calls == ["gdelt"]


@pytest.mark.unit
def test_merging_only_applies_to_news_methods():
    # Merging two OHLCV or fundamentals payloads would produce nonsense.
    vendor_methods = {
        "get_stock_data": {
            "gdelt": lambda *a, **k: "gdelt rows",
            "yfinance": lambda *a, **k: "yfinance rows",
        }
    }
    config = {
        "tool_vendors": {"get_stock_data": "gdelt,yfinance"},
        "data_vendors": {"core_stock_apis": "gdelt,yfinance"},
        "merged_news_vendors": ["gdelt", "yfinance"],
    }

    with patch("tradingagents.dataflows.interface.VENDOR_METHODS", vendor_methods):
        with patch("tradingagents.dataflows.interface.get_config", return_value=config):
            result = route_to_vendor("get_stock_data", "X", "2026-07-11", "2026-08-10")

    assert result == "gdelt rows"


@pytest.mark.unit
def test_global_news_chain_reaches_its_first_vendor_when_not_in_merge_set():
    """General regression guard for the class of bug diagnosed 2026-08-25
    (not a snapshot of the current default -- see tool_vendors.get_global_news
    in default_config.py, which has since moved to yfinance directly and no
    longer shapes its chain around this). The mechanism this guards: if a
    method's configured chain contains a vendor that is ALSO in
    merged_news_vendors (shared across get_news/get_global_news), that one
    vendor gets called via the merge pass, always "succeeds" (a vendor
    returning any string, e.g. yf.Search() which never errors), and
    route_to_vendor returns immediately -- every vendor placed BEFORE it in
    the configured chain is silently never attempted, even though it looks
    like it's first in line. Here: a vendor absent from merged_news_vendors
    must actually run when it's first in the chain."""

    def gdelt_success(*args, **kwargs):
        return "gdelt global news"

    def yfinance_should_never_be_called(*args, **kwargs):
        raise AssertionError("yfinance must not be reached for get_global_news")

    vendor_methods = {
        "get_global_news": {
            "gdelt": gdelt_success,
            "india_rss": lambda *a, **k: "india_rss global news",
            "yfinance": yfinance_should_never_be_called,
        }
    }
    # Mirrors the real shape: yfinance stays in merged_news_vendors (for
    # get_news's benefit) but is absent from get_global_news's own chain.
    config = {
        "tool_vendors": {"get_global_news": "gdelt,india_rss"},
        "data_vendors": {"news_data": "gdelt,india_rss"},
        "merged_news_vendors": ["google_news", "yfinance"],
    }

    with patch("tradingagents.dataflows.interface.VENDOR_METHODS", vendor_methods):
        with patch("tradingagents.dataflows.interface.get_config", return_value=config):
            result = route_to_vendor("get_global_news", "2026-08-25", None, None)

    assert result == "gdelt global news"


@pytest.mark.unit
def test_news_vendors_are_generic_equity_sources():
    news_vendors = set(VENDOR_METHODS["get_news"])
    global_news_vendors = set(VENDOR_METHODS["get_global_news"])

    generic_vendors = {"alpha_vantage", "finnhub", "gdelt", "yfinance"}
    assert generic_vendors.issubset(news_vendors)
    assert generic_vendors.issubset(global_news_vendors)
