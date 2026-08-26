# News Sources Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a real, verifiable "Sources" panel to the research page listing every news article the News/Sentiment reports were actually grounded in — the news-citation slice of the evidence-trace feature scoped out of the design-integration plan.

**Architecture:** The raw pre-fetched article text is already persisted verbatim inside `Reports.news`/`Reports.sentiment` (nothing about the analysis pipeline changes). A new pure-function parser (`api/news_sources.py`) recovers structured `NewsSource` entries from that text at **read time** (no DB migration, works retroactively on every existing run), a new field on `RunDetail` exposes them, and a new frontend component renders them using the mockup's evidence-card CSS.

**Tech Stack:** Python/Pydantic (backend, unchanged versions), `openapi-typescript` codegen (unchanged), React/Next.js (frontend, unchanged) — no new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-19-news-sources-design.md`. Read it for the full rationale (why this is safe, why the regex is reliable across vendors, why read-time computation beats write-time). This plan implements it task-by-task; the spec is the argument, this is the execution.

## Global Constraints

- **No backend prompt or agent-pipeline change of any kind.** Every fix here is in `api/`, never in `tradingagents/agents/`.
- **No DB schema/migration change.** `news_sources` is computed on read from the existing `reports` JSON column — do not add a column, do not touch `api/db.py`.
- **`extract_news_sources` must never raise.** Malformed/unrecognized text yields fewer (possibly zero) entries, never an exception. This is the same "never fabricate, never crash" discipline as `formatPrice`/`ratingIndex` from the prior plan.
- **`RunDetail.news_sources` is always a `list`, never `None`.** Empty list is a legitimate "nothing parsed" state.
- **Parsing scope: only the pre-fetched article sections**, never the LLM's own analysis prose (the text after `## News Analyst Report` / `## Sentiment Analyst Report`). This is what makes false-positive citations structurally impossible, not just unlikely — do not loosen it to scan the whole report string.
- **`SourcesPanel` renders nothing (not a placeholder) when its input list is empty** — same pattern as `RunHistoryPanel` returning `null` on a single-run page (`web/app/src/components/RunHistoryPanel.tsx`).
- **Reuse ported `.trace__*` CSS classes exactly as named** (`.trace__in`, `.trace__src`, `.trace__k`, `.trace__note`) — do not invent parallel class names for the same visual pattern.
- **Never add `Co-Authored-By: Claude` or any AI attribution** to commits (standing repo rule).
- Existing money-affecting API contract rules (`Verdict`/`TradeLevels` null-handling, 200 vs 202, rate-limit body) are unaffected by this change — do not touch `Verdict`, `TradeLevels`, or their extraction logic while editing `api/schemas.py`/`api/store.py`.

## File Structure

- Create: `api/news_sources.py` — `extract_news_sources(reports: Reports) -> list[NewsSource]`, pure function.
- Modify: `api/schemas.py` — add `NewsSource` model, add `RunDetail.news_sources` field.
- Modify: `api/store.py` — `_to_detail()` calls `extract_news_sources`.
- Modify: `api/openapi.json` — regenerated, not hand-edited.
- Create: `tests/test_news_sources.py` — parser unit tests (one fixture per vendor format).
- Create: `tests/test_store_news_sources.py` — `_to_detail()` wiring test.
- Modify: `web/app/src/lib/api-client/types.gen.ts` — regenerated, not hand-edited.
- Modify: `web/app/src/lib/api-client/client.ts` — export `NewsSource` type.
- Modify: `web/app/src/app/globals.css` — port `.trace__in`/`.trace__src`/`.trace__k`/`.trace__note`.
- Create: `web/app/src/components/research/SourcesPanel.tsx`.
- Create: `web/app/tests/unit/SourcesPanel.test.tsx`.
- Modify: `web/app/src/components/RunView.tsx` — mount `SourcesPanel`.

---

### Task 1: Backend schema + parser

**Files:**
- Modify: `api/schemas.py`
- Create: `api/news_sources.py`
- Create: `tests/test_news_sources.py`
- Modify: `api/openapi.json` (regenerated)

**Interfaces:**
- Produces: `NewsSource` (pydantic model: `title: str`, `source: str`, `published_date: str | None`, `url: str | None`, `snippet: str | None`), `extract_news_sources(reports: Reports) -> list[NewsSource]`.
- Consumes: `Reports` (existing, `api/schemas.py`) — reads `.news` and `.sentiment` string fields only.

- [ ] **Step 1: Add the `NewsSource` schema and `RunDetail` field**

In `api/schemas.py`, add this class immediately after `class Reports(BaseModel): ...` (before `class RunSummary`):

```python
class NewsSource(BaseModel):
    """One article the News or Sentiment report was actually given.

    Recovered from the pre-fetched article text those reports already
    embed verbatim — never a claim about which sentence in the report
    cites it, just "this was in the grounding set."
    """

    title: str
    source: str
    published_date: str | None = None
    url: str | None = None
    snippet: str | None = None
```

Then in `class RunDetail(RunSummary):`, add the field after `reports: Reports | None = None`:

```python
    news_sources: list[NewsSource] = Field(
        default_factory=list,
        description="Articles the News/Sentiment reports were grounded in. "
        "Always a list — empty means nothing parsed, not an error.",
    )
```

- [ ] **Step 2: Write the failing parser tests**

Create `tests/test_news_sources.py`:

```python
"""Guard for api.news_sources's citation parser.

The parser recovers structure from text that news_analyst.py and
sentiment_analyst.py already embed verbatim in their reports (the
pre-fetched article blocks). These fixtures are copied from the real
heading shape each vendor's ``_format_articles``/``format_articles``
emits (tradingagents/dataflows/rss.py, gdelt_news.py,
alpha_vantage_news.py, finnhub_news.py, yfinance_news.py) so a format
drift in any of them is caught here, not silently in production.
"""

import pytest

from api.news_sources import extract_news_sources
from api.schemas import Reports

_STANDARD_VENDOR_BLOCK = """## Pre-Fetched Company News Used

## SIEMENS.NS News from Google News, from 2026-07-10 to 2026-08-10
### Siemens India wins large order from state utility (source: Moneycontrol, 2026-08-08)
The order covers grid automation equipment across three states.
Link: https://example.com/siemens-order

### Siemens India Q3 profit rises 18% YoY (source: Economic Times, 2026-08-05)
Profit growth was driven by industrial automation demand.
Link: https://example.com/siemens-q3

## Pre-Fetched Global News Used

No global news available.

## News Analyst Report

The company posted strong Q3 numbers, with the order win from a state
utility (source: Moneycontrol, 2026-08-08) reinforcing the demand picture.
### This looks like a heading but is inside analyst prose (source: Nobody, 2026-01-01)
Link: https://should-not-be-parsed.example.com
"""

_YFINANCE_NO_DATE_BLOCK = """## Pre-Fetched Company News Used

## TCS.NS News from Yahoo Finance
### TCS announces buyback (source: Yahoo Finance)
Link: https://example.com/tcs-buyback

## News Analyst Report

Buyback announced.
"""

_NO_ARTICLES_BLOCK = """## Pre-Fetched Company News Used

No Google News articles found for TCS.NS between 2026-07-10 and 2026-08-10

## News Analyst Report

No notable news this period.
"""


@pytest.mark.unit
def test_parses_standard_vendor_heading_shape():
    reports = Reports(news=_STANDARD_VENDOR_BLOCK)

    sources = extract_news_sources(reports)

    assert len(sources) == 2
    first = sources[0]
    assert first.title == "Siemens India wins large order from state utility"
    assert first.source == "Moneycontrol"
    assert first.published_date == "2026-08-08"
    assert first.url == "https://example.com/siemens-order"
    assert "grid automation" in (first.snippet or "")

    # The LAST article in a block sits right before the next section's
    # "## ..." heading — regression guard for a real bug caught during
    # planning: that trailing section heading must never leak into this
    # article's snippet.
    second = sources[1]
    assert second.snippet == "Profit growth was driven by industrial automation demand."
    assert "Pre-Fetched Global News Used" not in (second.snippet or "")


@pytest.mark.unit
def test_never_parses_text_after_the_analyst_report_heading():
    reports = Reports(news=_STANDARD_VENDOR_BLOCK)

    sources = extract_news_sources(reports)

    assert all(s.source != "Nobody" for s in sources)
    assert len(sources) == 2  # not 3 — the prose-embedded fake heading is excluded


@pytest.mark.unit
def test_parses_yfinance_heading_with_no_date():
    reports = Reports(news=_YFINANCE_NO_DATE_BLOCK)

    sources = extract_news_sources(reports)

    assert len(sources) == 1
    assert sources[0].title == "TCS announces buyback"
    assert sources[0].source == "Yahoo Finance"
    assert sources[0].published_date is None


@pytest.mark.unit
def test_returns_empty_list_when_no_articles_present():
    reports = Reports(news=_NO_ARTICLES_BLOCK)

    assert extract_news_sources(reports) == []


@pytest.mark.unit
def test_returns_empty_list_for_missing_reports():
    assert extract_news_sources(Reports()) == []


@pytest.mark.unit
def test_dedupes_the_same_article_across_news_and_sentiment_reports():
    reports = Reports(news=_STANDARD_VENDOR_BLOCK, sentiment=_STANDARD_VENDOR_BLOCK)

    sources = extract_news_sources(reports)

    assert len(sources) == 2  # not 4 — same (title, source) pairs, deduped
```

- [ ] **Step 2b: Run tests to verify they fail**

Run: `python -m pytest tests/test_news_sources.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'api.news_sources'`) and `RunDetail`/`Reports` import errors resolve fine (schemas.py already patched in Step 1), but the module under test doesn't exist yet.

- [ ] **Step 3: Implement the parser**

Create `api/news_sources.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_news_sources.py -v`
Expected: PASS, all 6 tests.

- [ ] **Step 5: Regenerate the OpenAPI spec**

Run from the repo root:

```bash
python -c "import json; from api.main import app; json.dump(app.openapi(), open('api/openapi.json', 'w'), indent=2)"
git diff --stat api/openapi.json
```

Expected: `api/openapi.json` changes to include the `NewsSource` schema and `RunDetail.news_sources`. If the diff is empty, `api/schemas.py`'s edits in Step 1 did not take effect — stop and check the import path.

- [ ] **Step 6: Commit**

```bash
git add api/schemas.py api/news_sources.py api/openapi.json tests/test_news_sources.py
git commit -m "feat(api): add news source citation parser"
```

---

### Task 2: Wire the parser into the run-read path

**Files:**
- Modify: `api/store.py`
- Create: `tests/test_store_news_sources.py`

**Interfaces:**
- Consumes: `extract_news_sources` (Task 1, `api/news_sources.py`), `NewsSource` (Task 1, `api/schemas.py`).
- Produces: `RunDetail.news_sources` populated on every read through `_to_detail()`.

- [ ] **Step 1: Write the failing wiring test**

Create `tests/test_store_news_sources.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_store_news_sources.py -v`
Expected: FAIL — `detail.news_sources` does not exist as a populated field yet (defaults to `[]` from Task 1's schema default, so `test_to_detail_populates_news_sources_from_reports` fails; `test_to_detail_returns_empty_list_when_reports_is_none` passes vacuously). Confirm the first test fails before proceeding.

- [ ] **Step 3: Wire the parser into `_to_detail`**

In `api/store.py`, add the import:

```python
from api.news_sources import extract_news_sources
```

Replace `_to_detail`:

```python
def _to_detail(row: Run) -> RunDetail:
    reports = Reports.model_validate(row.reports) if row.reports else None
    return RunDetail(
        id=row.id,
        ticker=row.ticker,
        analysis_date=row.analysis_date,
        profile=AnalysisProfile(row.profile),
        status=RunStatus(row.status),
        created_at=row.created_at,
        completed_at=row.completed_at,
        error=row.error,
        verdict=Verdict.model_validate(row.verdict) if row.verdict else None,
        reports=reports,
        news_sources=extract_news_sources(reports) if reports else [],
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_store_news_sources.py tests/test_news_sources.py -v`
Expected: PASS, all 8 tests.

- [ ] **Step 5: Run the full backend test suite**

Run: `python -m pytest -v`
Expected: PASS — no regressions in `test_api_verdict_parsing.py` or any other existing test (nothing about `Verdict` extraction changed).

- [ ] **Step 6: Commit**

```bash
git add api/store.py tests/test_store_news_sources.py
git commit -m "feat(api): populate news_sources on run reads"
```

---

### Task 3: Frontend types + SourcesPanel component

**Files:**
- Modify: `web/app/src/lib/api-client/types.gen.ts` (regenerated)
- Modify: `web/app/src/lib/api-client/client.ts`
- Modify: `web/app/src/app/globals.css`
- Create: `web/app/src/components/research/SourcesPanel.tsx`
- Create: `web/app/tests/unit/SourcesPanel.test.tsx`

**Interfaces:**
- Consumes: `RunDetail.news_sources` (Task 2, backend, via regenerated types).
- Produces: `<SourcesPanel sources={NewsSource[]} />`, mounted by Task 4.

- [ ] **Step 1: Regenerate the typed client**

Run:

```bash
cd web/app
npm run generate:api-types
cd ../..
git diff --stat web/app/src/lib/api-client/types.gen.ts
```

Expected: the diff shows a new `NewsSource` entry under `components['schemas']` and a `news_sources` field added to `components['schemas']['RunDetail']`. If empty, Task 1's `api/openapi.json` regeneration did not happen or wasn't picked up — stop and check.

- [ ] **Step 2: Export the `NewsSource` type**

In `web/app/src/lib/api-client/client.ts`, add after the existing `export type Reports = ...` line:

```ts
export type NewsSource = components['schemas']['NewsSource'];
```

- [ ] **Step 3: Port the evidence-card CSS**

In `web/app/src/app/globals.css`, add (near the other `.rep*`/`.ledger`/`.duel` block-level component styles ported by the design-integration plan — append at the end of the file if there is no single obvious existing block to sit beside):

```css
/* ── News source citations ──────────────────────────────────────────
   Ported from web/design/research/index.html:134-141 (the evidence-trace
   card styling only — not .fig/.trace, which drive an inline-prose
   drill-down this panel does not use; see docs/superpowers/specs/
   2026-08-19-news-sources-design.md). */
.trace__in { margin-top: 16px; border: 1px solid #D3E1F7; background: #F6FAFF;
             border-radius: 14px; padding: 15px 17px; text-align: left; }
.trace__src { font-family: 'Inter Tight', sans-serif; font-size: .6875rem; font-weight: 900;
              letter-spacing: .085em; color: var(--accent-1); }
.trace__k { font-size: .8125rem; color: #676D80; margin-top: 9px; }
.trace__note { font-size: .8125rem; line-height: 1.55; color: #5A6070; margin-top: 7px; }
```

**Cascade-layer note (from the design-integration plan, recurring bug pattern):** these are unlayered custom classes, same as every other `.rep*`/`.trace*` class already in this file — they will beat Tailwind's `@layer utilities` classes in any specificity tie, which is the existing, intentional behavior of this file. No new risk here; just don't "fix" this by moving them into a layer.

- [ ] **Step 4: Write the failing component test**

Create `web/app/tests/unit/SourcesPanel.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { SourcesPanel } from '@/components/research/SourcesPanel';
import type { NewsSource } from '@/lib/api-client/client';

const source: NewsSource = {
  title: 'Example Corp posts results',
  source: 'Reuters',
  published_date: '2026-08-01',
  url: 'https://example.com/a',
  snippet: 'Results were in line with estimates.',
};

describe('SourcesPanel', () => {
  it('renders nothing when sources is empty', () => {
    const { container } = render(<SourcesPanel sources={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders a card per source with title linked to its url', () => {
    render(<SourcesPanel sources={[source]} />);

    expect(screen.getByText('Example Corp posts results')).toBeInTheDocument();
    expect(screen.getByText('Reuters')).toBeInTheDocument();
    const link = screen.getByRole('link', { name: 'Example Corp posts results' });
    expect(link).toHaveAttribute('href', 'https://example.com/a');
  });

  it('renders the title as plain text (no link) when url is absent', () => {
    render(<SourcesPanel sources={[{ ...source, url: null }]} />);

    expect(screen.getByText('Example Corp posts results')).toBeInTheDocument();
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 5: Run test to verify it fails**

Run: `cd web/app && npx vitest run tests/unit/SourcesPanel.test.tsx`
Expected: FAIL (`Failed to resolve import "@/components/research/SourcesPanel"`).

- [ ] **Step 6: Implement `SourcesPanel`**

Create `web/app/src/components/research/SourcesPanel.tsx`:

```tsx
import type { NewsSource } from '@/lib/api-client/client';

// Real citations for the News/Sentiment reports, not a drill-down: every
// entry is an article those reports were actually grounded in (see
// docs/superpowers/specs/2026-08-19-news-sources-design.md). Renders
// nothing when empty, matching RunHistoryPanel's null-render pattern —
// an empty citation list is a legitimate state, never a placeholder.
export function SourcesPanel({ sources }: { sources: NewsSource[] }) {
  if (sources.length === 0) return null;

  return (
    <section aria-label="News sources" className="mt-8 rounded-[28px] border border-[#E0E1E2] bg-white p-7 lg:p-9">
      <h2 className="font-tight font-black text-[#010101] text-2xl tracking-[-0.02em]">Sources</h2>
      <p className="copy text-[#6F6F6F] mt-1 measure">
        Every article the News and Sentiment reports above were actually given.
      </p>

      <div className="mt-4 grid gap-3">
        {sources.map((item, index) => (
          <div className="trace__in" key={`${item.source}-${item.title}-${index}`}>
            <p className="trace__src">{item.source.toUpperCase()}</p>
            <p className="trace__k">
              {item.url ? (
                <a href={item.url} target="_blank" rel="noreferrer">
                  {item.title}
                </a>
              ) : (
                item.title
              )}
            </p>
            {(item.published_date || item.snippet) && (
              <p className="trace__note">
                {item.published_date ? `${item.published_date} — ` : ''}
                {item.snippet}
              </p>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd web/app && npx vitest run tests/unit/SourcesPanel.test.tsx`
Expected: PASS, all 3 tests.

- [ ] **Step 8: Commit**

```bash
git add web/app/src/lib/api-client/types.gen.ts web/app/src/lib/api-client/client.ts \
        web/app/src/app/globals.css web/app/src/components/research/SourcesPanel.tsx \
        web/app/tests/unit/SourcesPanel.test.tsx
git commit -m "feat(web): add SourcesPanel component"
```

---

### Task 4: Mount in RunView and verify

**Files:**
- Modify: `web/app/src/components/RunView.tsx`

**Interfaces:**
- Consumes: `SourcesPanel` (Task 3), `current.news_sources` (Task 2, via `RunDetail`).

- [ ] **Step 1: Mount `SourcesPanel`**

In `web/app/src/components/RunView.tsx`, add the import:

```tsx
import { SourcesPanel } from './research/SourcesPanel';
```

Add it inside the completed-run grid, directly after `<ReportsRecord reports={current.reports ?? null} />` (same right-hand column `<div>`, so it sits beneath the report list it's evidence for):

```tsx
              <ReportsRecord reports={current.reports ?? null} />
              <SourcesPanel sources={current.news_sources} />
```

- [ ] **Step 2: Manual smoke check**

Run: `cd web/app && npm run build`
Expected: build succeeds with no type errors — `current.news_sources` must type-check as `NewsSource[]` against the regenerated `RunDetail` type from Task 3.

- [ ] **Step 3: Run full verification suite**

Run, from `web/app`:

```bash
npm run build
npm run lint
npx vitest run
npx playwright test
```

Expected: all four green. Playwright specs (`search-to-result.spec.ts`, `rate-limit.spec.ts`, `cached-run.spec.ts`) must still pass unmodified — this task only adds a new section to the completed-run DOM, it does not change any existing selector's structure. If a spec fails because it asserts on the full DOM shape of the completed-run grid, that is a real regression to fix, not a spec to loosen.

- [ ] **Step 4: Commit**

```bash
git add web/app/src/components/RunView.tsx
git commit -m "feat(web): mount SourcesPanel on the research page"
```
