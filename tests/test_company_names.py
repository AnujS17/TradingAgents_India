"""Company-name search-term resolution tests.

Text-matching sources (India-news RSS, Reddit) previously matched on the
ticker alone, plus a hardcoded 20-entry keyword map. Everything outside
those 20 large caps was matched as e.g. "LAURUSLABS" — a string no
publication ever prints — so mid-caps with real coverage were reported as
having no news and no discussion at all.
"""

import pytest

from tradingagents.dataflows.company_names import (
    _strip_corporate_suffix,
    base_symbol,
    clear_caches,
    company_search_terms,
)


@pytest.fixture(autouse=True)
def _reset_caches():
    clear_caches()
    yield
    clear_caches()


@pytest.fixture
def stub_name(monkeypatch):
    def _apply(name):
        monkeypatch.setattr(
            "tradingagents.dataflows.company_names.resolve_company_name",
            lambda ticker: name,
        )
        clear_caches()
    return _apply


@pytest.mark.unit
@pytest.mark.parametrize(
    "ticker,expected",
    [("RELIANCE.NS", "RELIANCE"), ("laurus.bo", "LAURUS"), ("NVDA", "NVDA")],
)
def test_base_symbol_strips_exchange_suffix(ticker, expected):
    assert base_symbol(ticker) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "name,expected",
    [
        ("Laurus Labs Limited", "Laurus Labs"),
        ("Tata Consultancy Services Limited", "Tata Consultancy Services"),
        ("NVIDIA Corporation", "NVIDIA"),
        ("Some Co Ltd.", "Some"),
    ],
)
def test_strip_corporate_suffix(name, expected):
    assert _strip_corporate_suffix(name) == expected


@pytest.mark.unit
def test_terms_include_ticker_cashtag_and_name(stub_name):
    stub_name("Laurus Labs Limited")
    terms = company_search_terms("LAURUSLABS.BO")

    assert terms == ("LAURUSLABS", "$LAURUSLABS", "Laurus Labs Limited", "Laurus Labs")


@pytest.mark.unit
def test_unresolvable_name_degrades_to_ticker_only(stub_name):
    # yfinance being down must not break matching outright — the ticker terms
    # still work, they are just less effective.
    stub_name("")
    assert company_search_terms("LAURUSLABS.BO") == ("LAURUSLABS", "$LAURUSLABS")


@pytest.mark.unit
def test_curated_aliases_supplement_resolved_name(stub_name):
    # "RIL" is what Indian media actually write; no API returns it.
    stub_name("Reliance Industries Limited")
    terms = company_search_terms("RELIANCE.NS")

    assert "RIL" in terms
    assert "Reliance Industries" in terms


@pytest.mark.unit
def test_short_name_fragments_are_not_used_as_terms(stub_name):
    # A 3-char fragment would substring-match unrelated prose everywhere; the
    # exact ticker already covers that case.
    stub_name("ITC Limited")
    terms = company_search_terms("ITC.NS")

    assert "ITC" in terms  # the ticker itself, still present
    assert all(len(t) >= 4 or t.upper() == "ITC" or t.startswith("$") for t in terms)


@pytest.mark.unit
def test_terms_are_deduplicated_case_insensitively(stub_name):
    stub_name("LAURUSLABS")
    terms = company_search_terms("LAURUSLABS.BO")

    lowered = [t.lower() for t in terms]
    assert len(lowered) == len(set(lowered))
