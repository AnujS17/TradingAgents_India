"""Recovers structured news citations from already-persisted report text.

news_analyst.py and sentiment_analyst.py embed the exact pre-fetched
article blocks they were grounded in, verbatim, into the strings that
become Reports.news / Reports.sentiment — see the "## Pre-Fetched ...
Used" headings each one writes. That text is already saved to the
database on every completed run. This module only recovers structure
from data already proven to have been given to the model; it never
invents a source and never scans the model's own prose.
"""

from __future__ import annotations

import re

from api.schemas import NewsSource, Reports

# Every news vendor (tradingagents/dataflows/rss.py::format_articles,
# gdelt_news.py, alpha_vantage_news.py, finnhub_news.py — each with a
# local ``_format_articles``; yfinance_news.py inline) renders one of:
#   ### {title} (source: {source}, {date})
#   ### {title} (source: {source})            <- yfinance, no date
_ARTICLE_HEADING = re.compile(
    r"^### (?P<title>.+?) \(source: (?P<source>[^,)]+)(?:, (?P<date>[^)]+))?\)\s*$"
)
_LINK_LINE = re.compile(r"^Link: (?P<url>\S+)\s*$")
# Any markdown heading line, article or not — used to bound an article's
# body so a non-article heading right after it (e.g. the next vendor's
# "## Pre-Fetched Global News Used" block) never leaks into the previous
# article's snippet.
_HEADING_LINE = re.compile(r"^#+\s")

# Both analyst nodes append this heading before their own analysis text
# (news_analyst.py: "## News Analyst Report"; sentiment_analyst.py:
# "## Sentiment Analyst Report"). Everything before it is pre-fetched
# data; everything after it is the model's own writing, and is never
# scanned — that is what makes a false-positive citation structurally
# impossible here, not just unlikely.
_PREFETCHED_SECTION_END = re.compile(
    r"^## (?:News|Sentiment) Analyst Report\s*$", re.MULTILINE
)


def _prefetched_text(raw: str) -> str:
    match = _PREFETCHED_SECTION_END.search(raw)
    return raw[: match.start()] if match else raw


def _parse_articles(text: str) -> list[NewsSource]:
    lines = text.splitlines()
    article_headings: list[tuple[int, re.Match]] = []
    # Boundary = any heading line (article or section). An article's body
    # stops at the NEXT heading of any kind, not just the next article —
    # otherwise a trailing section heading (e.g. "## Pre-Fetched Global
    # News Used" right after the last article in a block) gets swept into
    # that article's snippet.
    boundaries: list[int] = []
    for i, line in enumerate(lines):
        match = _ARTICLE_HEADING.match(line)
        if match:
            article_headings.append((i, match))
            boundaries.append(i)
        elif _HEADING_LINE.match(line):
            boundaries.append(i)
    boundaries.append(len(lines))
    boundaries.sort()

    sources: list[NewsSource] = []
    for line_no, match in article_headings:
        end = next(b for b in boundaries if b > line_no)
        body_lines = [ln for ln in lines[line_no + 1 : end] if ln.strip()]

        url: str | None = None
        snippet_lines: list[str] = []
        for ln in body_lines:
            link_match = _LINK_LINE.match(ln)
            if link_match:
                url = link_match.group("url")
            else:
                snippet_lines.append(ln)

        snippet = " ".join(snippet_lines).strip()[:500] or None
        date = match.group("date")
        sources.append(
            NewsSource(
                title=match.group("title").strip(),
                source=match.group("source").strip(),
                published_date=date.strip() if date else None,
                url=url,
                snippet=snippet,
            )
        )
    return sources


def extract_news_sources(reports: Reports) -> list[NewsSource]:
    """Structured citations for the News and Sentiment reports.

    Never raises. Text that doesn't match the expected heading shape
    contributes zero entries for that block, not an error.
    """
    sources: list[NewsSource] = []
    seen: set[tuple[str, str]] = set()
    for raw in (reports.news, reports.sentiment):
        if not raw:
            continue
        for entry in _parse_articles(_prefetched_text(raw)):
            key = (entry.title.lower(), entry.source.lower())
            if key in seen:
                continue
            seen.add(key)
            sources.append(entry)
    return sources
