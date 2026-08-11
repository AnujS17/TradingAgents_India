from unittest.mock import MagicMock, patch

import pytest

from tradingagents.dataflows.company_names import clear_caches
from tradingagents.dataflows.reddit import (
    DEFAULT_SUBREDDITS,
    _fetch_subreddit,
    _query_variants,
    fetch_reddit_posts,
)


@pytest.mark.unit
def test_reddit_fetcher_uses_json_fallback_when_praw_unavailable():
    response = MagicMock()
    response.status_code = 200
    # Content-Type must look like JSON: the fetcher now uses it to tell a real
    # payload from Reddit's HTML block page, which old.reddit.com serves with
    # HTTP 200 (see _json_payload_or_none).
    response.headers = {"Content-Type": "application/json; charset=UTF-8"}
    response.json.return_value = {
        "data": {
            "children": [
                {
                    "data": {
                        "id": "abc123",
                        "title": "NVDA AI capex setup",
                        "score": 42,
                        "num_comments": 7,
                        "created_utc": 1_800_000_000,
                        "selftext": "ETF flow discussion",
                    }
                }
            ]
        }
    }
    response.raise_for_status.return_value = None

    session = MagicMock()
    session.get.return_value = response

    with patch("tradingagents.dataflows.reddit._get_reddit_client", side_effect=ImportError("Run: pip install praw")):
        with patch("tradingagents.dataflows.reddit.requests.Session", return_value=session):
            result = fetch_reddit_posts("NVDA", subreddits=("stocks",), limit_per_sub=5)

    assert "NVDA AI capex setup" in result
    assert "r/stocks" in result
    headers = session.headers.update.call_args.args[0]
    assert "Mozilla/5.0" in headers["User-Agent"]


@pytest.fixture
def stub_company_name(monkeypatch):
    """Pin the resolved company name so these stay offline and deterministic.

    company_search_terms resolves names through yfinance; without this the
    assertions below would depend on a live network call and on whatever
    Yahoo currently returns for the symbol.
    """
    def _apply(name: str):
        monkeypatch.setattr(
            "tradingagents.dataflows.company_names.resolve_company_name",
            lambda ticker: name,
        )
        clear_caches()

    clear_caches()
    yield _apply
    clear_caches()


@pytest.mark.unit
def test_query_variants_strips_nse_bse_suffix(stub_company_name):
    # RELIANCE.NS essentially never appears verbatim in casual Reddit posts —
    # retail traders write "RELIANCE" or "$RELIANCE" — so search terms must
    # be built from the base symbol, not the exchange-qualified ticker.
    stub_company_name("Reliance Industries Limited")
    variants = _query_variants("RELIANCE.NS")

    assert variants[:2] == ["RELIANCE", "$RELIANCE"]
    assert "RELIANCE.NS" not in variants


@pytest.mark.unit
def test_query_variants_include_company_name(stub_company_name):
    # Symbol-only search is why a mid-cap with active coverage reported zero
    # Reddit discussion: posts say "Laurus Labs", never "LAURUSLABS". Both the
    # full name and the suffix-stripped form must be searchable.
    stub_company_name("Laurus Labs Limited")
    variants = _query_variants("LAURUSLABS.BO")

    assert "Laurus Labs Limited" in variants
    assert "Laurus Labs" in variants


@pytest.mark.unit
def test_query_variants_unsuffixed_ticker_unchanged(stub_company_name):
    stub_company_name("")
    assert _query_variants("NVDA") == ["NVDA", "$NVDA"]


class FakePost:
    def __init__(self, pid, title, selftext=""):
        self.id = pid
        self.title = title
        self.selftext = selftext
        self.score = 1
        self.num_comments = 0
        self.created_utc = 1_800_000_000


class FakeSubreddit:
    def __init__(self, search_results):
        self._search_results = search_results

    def search(self, query, **kwargs):
        return list(self._search_results)

    def new(self, limit=50):
        return []

    def hot(self, limit=50):
        return []


class FakeReddit:
    def __init__(self, search_results):
        self._sub = FakeSubreddit(search_results)

    def subreddit(self, name):
        return self._sub


@pytest.mark.unit
def test_search_results_not_mentioning_ticker_are_discarded(stub_company_name):
    # Reddit's search is not a filter. Searching r/IndianStockMarket for "TMPV"
    # returned generic portfolio-review threads containing neither "TMPV" nor
    # "Tata", and the search leg appended them verbatim — so the sentiment
    # prompt was handed portfolio chatter labelled "posts mentioning TMPV.NS"
    # (observed live, TMPV.NS run 2026-08-10).
    stub_company_name("Tata Motors Passenger Vehicles Limited")
    reddit = FakeReddit([
        FakePost("a", "Please give an expert advice on my portfolio"),
        FakePost("b", "Portfolio review", "22m, been investing since a couple of months"),
    ])

    posts = _fetch_subreddit(reddit, "TMPV.NS", "IndianStockMarket", 5)

    assert posts == []


@pytest.mark.unit
def test_search_results_mentioning_ticker_are_kept(stub_company_name):
    stub_company_name("Tata Motors Passenger Vehicles Limited")
    reddit = FakeReddit([
        FakePost("a", "Unrelated portfolio review"),
        FakePost("b", "Thoughts on TMPV after the JLR guidance cut?"),
        FakePost("c", "Bought more", "Added Tata Motors Passenger Vehicles this week"),
    ])

    posts = _fetch_subreddit(reddit, "TMPV.NS", "IndianStockMarket", 5)

    titles = [p["title"] for p in posts]
    assert "Thoughts on TMPV after the JLR guidance cut?" in titles
    assert "Bought more" in titles
    assert "Unrelated portfolio review" not in titles


@pytest.mark.unit
def test_verification_matches_body_not_only_title(stub_company_name):
    stub_company_name("Tata Motors Passenger Vehicles Limited")
    reddit = FakeReddit([FakePost("a", "views on this", "also added TMPV 12 shares")])

    posts = _fetch_subreddit(reddit, "TMPV.NS", "NSEbets", 5)

    assert len(posts) == 1


@pytest.mark.unit
def test_default_subreddits_are_india_focused():
    # r/stocks and r/investing are US-equity boards: for an NSE/BSE ticker they
    # cost a round-trip each and essentially never carry the symbol.
    assert "stocks" not in DEFAULT_SUBREDDITS
    assert "investing" not in DEFAULT_SUBREDDITS
    assert "IndianStockMarket" in DEFAULT_SUBREDDITS
    assert all("india" in s.lower() or s in {"NSEbets", "DalalStreetTalks", "StockMarketIndia"}
               for s in DEFAULT_SUBREDDITS)
