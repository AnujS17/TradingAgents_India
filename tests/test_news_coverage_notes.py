"""Company-specificity note tests for vendor news.

Yahoo's per-ticker feed carries sector and peer coverage. The only "company
news" it returned for TMPV.NS on 2026-08-10 was a Mahindra & Mahindra earnings
story, which the news analyst then reasoned over as TMPV's own news. The fix
counts how many articles actually name the company rather than labelling
individual articles — an article may legitimately use a name we did not
resolve (TMPV is written "Tata Motors" in the press), so per-article tagging
would produce confident mislabels.
"""

import pytest

from tradingagents.dataflows.company_names import clear_caches
from tradingagents.dataflows.yfinance_news import _company_specificity_note


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
def test_note_flags_peer_only_coverage(stub_name):
    stub_name("Tata Motors Passenger Vehicles Limited")
    note = _company_specificity_note(
        "TMPV.NS",
        [{"title": "India's Mahindra posts quarterly profit rise", "summary": "SUV demand"}],
    )

    assert "0 of 1" in note
    assert "peer coverage" in note


@pytest.mark.unit
def test_no_note_when_every_article_names_the_company(stub_name):
    # A clean feed must not be cluttered with a warning that does not apply.
    stub_name("Tata Motors Passenger Vehicles Limited")
    note = _company_specificity_note(
        "TMPV.NS",
        [{"title": "TMPV July sales climb 59%", "summary": ""}],
    )

    assert note == ""


@pytest.mark.unit
def test_note_counts_partial_coverage(stub_name):
    stub_name("Tata Motors Passenger Vehicles Limited")
    note = _company_specificity_note(
        "TMPV.NS",
        [
            {"title": "TMPV July sales climb 59%", "summary": ""},
            {"title": "Mahindra profit rises", "summary": ""},
            {"title": "Auto sector outlook", "summary": ""},
        ],
    )

    assert "1 of 3" in note


@pytest.mark.unit
def test_match_may_come_from_summary(stub_name):
    stub_name("Tata Motors Passenger Vehicles Limited")
    note = _company_specificity_note(
        "TMPV.NS",
        [{"title": "Auto majors report", "summary": "Tata Motors Passenger Vehicles led gains"}],
    )

    assert note == ""


@pytest.mark.unit
def test_no_note_for_empty_article_list(stub_name):
    stub_name("Tata Motors Passenger Vehicles Limited")

    assert _company_specificity_note("TMPV.NS", []) == ""


@pytest.mark.unit
def test_unresolvable_company_still_matches_on_ticker(stub_name):
    stub_name("")
    note = _company_specificity_note("TMPV.NS", [{"title": "TMPV rallies", "summary": ""}])

    assert note == ""
