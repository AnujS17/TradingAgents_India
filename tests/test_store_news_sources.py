"""Guard that api.store._to_detail() actually calls the news-sources
parser — Task 1 tested the parser in isolation; this tests the wiring."""

from datetime import date, datetime, timezone

import pytest

from api.db import Run
from api.store import _to_detail

_NEWS_WITH_ONE_ARTICLE = """## Pre-Fetched Company News Used

### Example Corp posts results (source: Reuters, 2026-08-01)
Link: https://example.com/a

## News Analyst Report

Results were fine.
"""


def _row(**overrides) -> Run:
    defaults = dict(
        id="r1",
        ticker="EXAMPLE.NS",
        analysis_date=date(2026, 8, 1),
        profile="fast",
        status="completed",
        created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        completed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        error=None,
        verdict=None,
        reports={"news": _NEWS_WITH_ONE_ARTICLE},
        refresh_data=False,
        requested_by=None,
    )
    defaults.update(overrides)
    return Run(**defaults)


@pytest.mark.unit
def test_to_detail_populates_news_sources_from_reports():
    detail = _to_detail(_row())

    assert len(detail.news_sources) == 1
    assert detail.news_sources[0].title == "Example Corp posts results"


@pytest.mark.unit
def test_to_detail_returns_empty_list_when_reports_is_none():
    detail = _to_detail(_row(reports=None))

    assert detail.news_sources == []
