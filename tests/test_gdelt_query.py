"""GDELT query-construction regression tests.

GDELT is *first* in the news vendor chain, and it was querying a string that
never appears in news prose: ``("LAURUSLABS.BO" OR "LAURUSLABS.BO")`` — both
halves identical whenever the ticker is already uppercase, and no article
ever contains an exchange-suffixed symbol. Confirmed live on 2026-08-10:
that query returned 0 articles while ``("LAURUSLABS" OR "Laurus Labs")``
returned 30, including "Laurus Labs surges past Rs 1 lakh crore MCAP"
(2026-08-05) — a material story that sat *inside* the window the
LAURUSLABS.BO run reported as having no company news at all.
"""

import pytest

from tradingagents.dataflows.company_names import (
    clear_caches,
    company_search_terms,
    news_query_terms,
    news_search_terms,
)
from tradingagents.dataflows.gdelt_news import _build_ticker_query


@pytest.fixture
def stub_name(monkeypatch):
    def _apply(name):
        monkeypatch.setattr(
            "tradingagents.dataflows.company_names.resolve_company_name",
            lambda ticker: name,
        )
        clear_caches()

    clear_caches()
    yield _apply
    clear_caches()


@pytest.mark.unit
def test_query_no_longer_contains_exchange_suffix(stub_name):
    stub_name("Laurus Labs Limited")
    query = _build_ticker_query("LAURUSLABS.BO")

    assert ".BO" not in query
    assert ".NS" not in query


@pytest.mark.unit
def test_query_searches_company_name_only_when_resolved(stub_name):
    # The bare ticker is a fallback, not a standing OR-term (see
    # test_news_terms_drop_bare_ticker_once_a_name_resolves below for why):
    # once a name resolves, it is the only term sent.
    stub_name("Laurus Labs Limited")
    assert _build_ticker_query("LAURUSLABS.BO") == '("Laurus Labs")'


@pytest.mark.unit
def test_query_is_parenthesised_for_ord_terms(stub_name):
    # GDELT returns "Queries containing OR'd terms must be surrounded by ()."
    # as a plain-text 200 if this is missing, which parses as zero articles.
    stub_name("Laurus Labs Limited")
    query = _build_ticker_query("LAURUSLABS.BO")

    assert query.startswith("(") and query.endswith(")")


@pytest.mark.unit
def test_query_has_no_duplicate_terms(stub_name):
    # The old query OR'd the ticker with itself.
    stub_name("Laurus Labs Limited")
    terms = _build_ticker_query("LAURUSLABS.BO").strip("()").split(" OR ")

    assert len(terms) == len(set(terms))


@pytest.mark.unit
def test_query_falls_back_to_ticker_when_name_unresolvable(stub_name):
    # yfinance down must not produce an empty "()" query.
    stub_name("")
    assert _build_ticker_query("LAURUSLABS.BO") == '("LAURUSLABS")'


@pytest.mark.unit
def test_news_terms_exclude_cashtag(stub_name):
    # "$LAURUSLABS" is a StockTwits/Reddit convention, absent from news prose.
    stub_name("Laurus Labs Limited")

    assert any(t.startswith("$") for t in company_search_terms("LAURUSLABS.BO"))
    assert not any(t.startswith("$") for t in news_search_terms("LAURUSLABS.BO"))


@pytest.mark.unit
def test_news_terms_drop_name_subsumed_by_shorter_phrase(stub_name):
    # Phrase search for "Laurus Labs" already matches "Laurus Labs Limited";
    # sending both is pure query padding.
    stub_name("Laurus Labs Limited")
    terms = news_search_terms("LAURUSLABS.BO")

    assert "Laurus Labs" in terms
    assert "Laurus Labs Limited" not in terms


@pytest.mark.unit
def test_news_terms_keep_curated_aliases(stub_name):
    stub_name("Reliance Industries Limited")
    terms = news_search_terms("RELIANCE.NS")

    assert "RIL" in terms
    assert "Reliance Industries" in terms


@pytest.mark.unit
def test_query_terms_drop_bare_ticker_once_a_name_resolves(stub_name):
    # The actual bug: "HAL" is Halliburton's NYSE ticker AND the DC Comics
    # character (Hal Jordan). OR'd in unconditionally alongside "Hindustan
    # Aeronautics", it pulled Halliburton earnings stories and "Lanterns"
    # recaps into a Hindustan Aeronautics Limited run's news/sources. This is
    # news_query_terms specifically -- an unscoped web search -- not
    # news_search_terms, which still keeps the bare ticker for matching
    # against yfinance's already ticker-scoped per-symbol feed.
    stub_name("Hindustan Aeronautics Limited")
    terms = news_query_terms("HAL.NS")

    assert "HAL" not in terms
    assert "Hindustan Aeronautics" in terms


@pytest.mark.unit
def test_query_terms_fall_back_to_bare_ticker_when_name_unresolvable(stub_name):
    # No name at all is the one case the bare ticker must still cover --
    # some outlets write only the symbol, and there is nothing else to search.
    stub_name("")
    terms = news_query_terms("LAURUSLABS.BO")

    assert terms == ("LAURUSLABS",)


@pytest.mark.unit
def test_search_terms_keep_bare_ticker_for_the_scoped_specificity_check(stub_name):
    # news_search_terms (yfinance's already ticker-scoped feed) must NOT
    # change -- _company_specificity_note relies on the bare ticker matching
    # real self-mentions like "TMPV July sales climb 59%".
    stub_name("Hindustan Aeronautics Limited")
    terms = news_search_terms("HAL.NS")

    assert "HAL" in terms
