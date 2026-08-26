"""Recovers structured news citations from already-persisted report text.

news_analyst.py and sentiment_analyst.py embed the exact pre-fetched
article blocks they were grounded in, verbatim, into the strings that
become Reports.news / Reports.sentiment — see the "## Pre-Fetched ...
Used" headings each one writes. That text is already saved to the
database on every completed run. This module only recovers structure
from data already proven to have been given to the model; it never
invents a source and never scans the model's own prose.

Scoped to company-specific evidence only. news_report also embeds a
ticker-agnostic "Pre-Fetched Global News Used" section (and, after it,
India-market and exchange-filing sections) — real input the model saw, but
market/macro backdrop rather than evidence about the company being
analysed, so it is excluded here even though it was "actually given" in
the literal sense (see _prefetched_text).
"""

from __future__ import annotations

import re

from api.schemas import NewsSource, Reports

# These producers of Reports.news / Reports.sentiment render one of:
#   ### {title} (source: {source}, {date})
#   ### {title} (source: {source})            <- yfinance, no date
# Confirmed producers: tradingagents/dataflows/rss.py::format_articles
# (google_news), gdelt_news.py and india_news.py (each with a local
# ``_format_articles``, byte-identical shape), finnhub_news.py (local
# ``_format_articles``), yfinance_news.py (inline, no date in heading), and
# alpha_vantage_news.py (local ``_format_articles``, added 2026-08-25 when
# alpha_vantage was promoted to the primary get_global_news vendor -- it
# used to return NEWS_SENTIMENT's raw JSON verbatim instead of this shape,
# which this parser correctly yielded zero citations for; not an issue
# while that vendor was rarely reached, but a real gap once it was
# actually in the loop).
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

# news_report also embeds a "Pre-Fetched Global News Used" section (and,
# after it, "Pre-Fetched India-Market News Used" / "...Exchange Filings
# Used") before the boundary above -- ticker-agnostic market/macro
# backdrop, not evidence about the specific company being analysed. Only
# sentiment_analyst.py has no such heading (its own pre-fetched blocks —
# StockTwits, Reddit, ticker-filtered India news — are already
# company-scoped), so this only ever truncates news_report.
_NEWS_GLOBAL_SECTION_START = re.compile(
    r"^## Pre-Fetched Global News Used\s*$", re.MULTILINE
)

# What the "date" capture group of _ARTICLE_HEADING looks like when it is
# actually a date: either the real formatters' "%Y-%m-%d" output, or their
# literal "date unknown" fallback (rss.py/finnhub_news.py/gdelt_news.py/
# india_news.py all emit one of these two). Anything else in that group
# — e.g. the tail of a publisher name that itself contains a comma, on the
# no-date yfinance heading shape — is not a date at all; see
# _split_source_and_date below.
_DATE_SHAPE = re.compile(r"^\d{4}-\d{2}-\d{2}$|^date unknown$", re.IGNORECASE)


def _prefetched_text(raw: str) -> str:
    """Text between the start of the report and the analyst's own prose,
    further narrowed to company-specific pre-fetched data only.

    Every report ever persisted has the boundary heading (verified via git
    history), but that is an accident of what has existed so far, not a
    structural guarantee. Fail closed: if the boundary is missing, treat
    NONE of the text as pre-fetched data rather than risk scanning the
    model's own prose for "### ..." look-alikes.

    Within that span, news_report also carries global/macro sections that
    are given to the model but are not evidence about the specific company
    — truncate there too when present (see _NEWS_GLOBAL_SECTION_START).
    """
    end_match = _PREFETCHED_SECTION_END.search(raw)
    if end_match is None:
        return ""
    prefetched = raw[: end_match.start()]

    global_match = _NEWS_GLOBAL_SECTION_START.search(prefetched)
    return prefetched[: global_match.start()] if global_match else prefetched


def _split_source_and_date(source: str, date: str | None) -> tuple[str, str | None]:
    """Guards against a comma inside a publisher name being misread as a
    date separator on the no-date (yfinance) heading shape, e.g.
    ``### Deal signed (source: Dow Jones, Inc.)`` — ``_ARTICLE_HEADING``'s
    optional date group greedily captures "Inc." there. If what was
    captured as "date" doesn't actually look like a date, it was really
    the rest of the source name: fold it back in and report no date."""
    if date is not None and not _DATE_SHAPE.match(date.strip()):
        return f"{source}, {date}".strip(), None
    return source, date


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
        source, date = _split_source_and_date(
            match.group("source").strip(), date.strip() if date else None
        )
        sources.append(
            NewsSource(
                title=match.group("title").strip(),
                source=source,
                published_date=date,
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
