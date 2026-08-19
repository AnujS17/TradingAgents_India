# News Sources Panel — Design Spec

## Goal

Surface real, verifiable citations for news articles behind the News and
Sentiment reports on the research page — the first of the four features
scoped out during the design-integration effort (`web/design/DESIGN.md`'s
"Status update" section). Technical-indicator citations and inline
per-claim linking are explicitly out of scope for this iteration (see
"Non-goals" and `tradingagentsv2.md`).

## Background

The design mockup (`web/design/research/index.html`) includes an
"evidence trace" UI where clicking a figure inline in the prose opens a
sourced value card. That pattern requires the text-writing agent to emit
citation markers it can vouch for — feasible for a fixed indicator series,
not something that can be reconstructed after the fact for LLM-written
prose without risking a false or stale link (see DESIGN.md's "Scope
discipline: only trace a figure that reconciles").

News is different: `news_analyst.py` and `sentiment_analyst.py` are
instructed to ground their reports *only* in a fixed, pre-fetched article
list ("Pre-fetched news data is provided below; ground your report only
in it. Do not call or imply additional news tools were used."). That list
is deterministic — it exists before the LLM is invoked — so listing
"every article this report was actually given" carries zero hallucination
risk, by construction.

**Key finding that keeps this small:** the full pre-fetched article text
is *already persisted*. Both analyst nodes embed their raw fetched blocks
verbatim into the string they return (`news_report` / `sentiment_report`),
under headings like `## Pre-Fetched Company News Used`. `api/service.py`'s
`_extract_reports()` already saves that whole string into the `reports`
JSON column on every run — including every run already in the database.
No new data capture, no agent/prompt change, no pipeline change, no DB
migration is needed. This feature is a parser over data that already
exists at rest.

**Format consistency across vendors:** `news_data` fans out across 5
vendors (`google_news`, `yfinance`, `gdelt`, `alpha_vantage`, `finnhub`
— `tradingagents/default_config.py`'s fallback chain), plus the
supplemental `india_news` module. Confirmed by reading each vendor
module:

| Vendor | Formatter | Heading shape |
|---|---|---|
| google_news | `tradingagents/dataflows/rss.py::format_articles` | `### {title} (source: {source}, {date})` + optional `Link: {url}` |
| gdelt_news | local `_format_articles` | same shape (verified byte-identical pattern) |
| alpha_vantage_news | `_make_api_request` (raw passthrough) | **does NOT match** — returns raw, unformatted vendor API JSON, no `### heading` block at all. If the fallback chain reaches it, the parser correctly yields zero citations for that text; this is accepted degradation, not a bug. |
| finnhub_news | local `_format_articles` | same shape |
| yfinance_news | inline in `get_news_yfinance` | `### {title} (source: {publisher})` (no date in heading) + optional `Link: {url}` |
| india_news | local `_format_articles` (`tradingagents/dataflows/india_news.py`) | same shape as google_news/gdelt/finnhub. Supplemental, not part of the vendor fallback chain, but IS exercised in production — India-news block citations show up in real sentiment reports. |

One regex, tolerant of the missing-date variant, covers every vendor in
the fallback chain except alpha_vantage_news, plus india_news.

## Architecture

### 1. Backend parser — `api/news_sources.py` (new)

Pure function, no I/O, no LLM:

```python
def extract_news_sources(reports: Reports) -> list[NewsSource]:
```

- Runs only against the **pre-fetched section** of `reports.news` and
  `reports.sentiment` — i.e. the text between a `## Pre-Fetched ... News
  Used` heading and the next `## ... Analyst Report` heading (or global
  news / India-market / exchange-filings sub-headings in between, which
  are also pre-fetched news-shaped content). Text after `## News Analyst
  Report` / `## Sentiment Analyst Report` (the LLM's own prose) is never
  scanned — this is what makes false positives structurally impossible,
  not just unlikely.
- Regex: `### (?P<title>.+?) \(source: (?P<source>[^,)]+)(?:, (?P<date>[^)]+))?\)`,
  with the following non-blank line checked for a `Link: (?P<url>...)`
  prefix, and the line(s) between the heading and the `Link:`/next
  heading captured as an optional snippet (truncated the same way the
  formatters already truncate summaries: 500 chars).
- Dedupes by `(title, source)` — the same article can legitimately appear
  in both the company-news and global-news blocks of the same report, or
  in both `reports.news` and `reports.sentiment` (they share the same
  `get_news` window).
- Never raises. A block that doesn't match the pattern (exchange filings,
  StockTwits, Reddit — deliberately excluded, not "news articles" in the
  citation sense) contributes zero entries, not an error.

### 2. Schema — `api/schemas.py`

```python
class NewsSource(BaseModel):
    title: str
    source: str
    published_date: str | None = None
    url: str | None = None
    snippet: str | None = None
```

`RunDetail` gains:

```python
news_sources: list[NewsSource] = Field(default_factory=list)
```

Always a list, never `None` — an empty list is a legitimate "nothing
parsed" state, rendered identically to "no citations available," never
surfaced as an error.

### 3. Wiring — `api/store.py`

`_to_detail()` calls `extract_news_sources(reports)` when building the
`RunDetail` response, using the row's existing `reports` JSON. Computed
on read, not on write:

- No DB migration, no new column.
- Works retroactively on every run already in the database — not just
  future ones.
- Trades a small amount of per-read CPU (regex over a few KB of text) for
  zero backfill risk. Reads are infrequent (poll-based, human-paced), so
  this is the right trade.

### 4. Frontend — `web/app/src/components/research/SourcesPanel.tsx` (new)

- Props: `{ sources: NewsSource[] }`.
- Renders nothing when `sources` is empty — same pattern as
  `RunHistoryPanel` returning `null` on a single-run page. Never render an
  empty-state placeholder for a section that legitimately has no data.
- Visual language ports the mockup's evidence-card CSS (`web/design/
  research/index.html:134-141` — `.trace__in`, `.trace__src`, `.trace__k`,
  `.trace__note`) into `web/app/src/app/globals.css`. **Verified not
  already present** — the design-integration plan scoped evidence-trace
  out entirely, so only the card styling is ported now, not the `.fig`/
  `.trace` collapsible-drill-down mechanics (those exist to open a panel
  from a button embedded in prose; this panel is a static list, not an
  inline drill-down, so that JS toggle machinery does not apply here):
  `source` maps to `.trace__src`, `title` (linked to `url` when present)
  maps to `.trace__k`, `published_date` + `snippet` map to `.trace__note`.
- Mounted in `web/app/src/components/RunView.tsx`, inside the existing
  completed-run grid, near `ReportsRecord` (the News/Sentiment report
  rows this panel is evidence for).
- `web/app/src/lib/api-client/client.ts` (or wherever `RunDetail`'s type
  is declared/generated): add `news_sources: NewsSource[]` to the type.

## Data flow

```
run completes
  -> news_analyst_node / sentiment_analyst_node already embed
     pre-fetched article text into news_report / sentiment_report
  -> api/service.py::_extract_reports() saves that text into
     Reports.news / Reports.sentiment (UNCHANGED — already happens today)
  -> api/store.py::mark_completed() persists Reports as JSON (UNCHANGED)
  -> [later] api/store.py::_to_detail() reads the row
       -> api/news_sources.py::extract_news_sources(reports) parses
          the pre-fetched sections into list[NewsSource]
       -> RunDetail.news_sources populated
  -> frontend renders SourcesPanel from run.news_sources
```

## Error handling

The parser never throws; it returns fewer (possibly zero) entries for
text it doesn't recognize. No new failure mode reaches the run pipeline,
the worker, or the queue — nothing about *running* an analysis changes.
A malformed or unexpected vendor format degrades to "no sources shown,"
never a wrong or fabricated one.

## Testing

- **Backend (real tests, not light-touch):** `extract_news_sources` is a
  pure function — cheap and deterministic to test properly regardless of
  the "light testing" instruction that governed the design-integration
  plan. One fixture per vendor format (4 identical-shape vendors + the
  yfinance no-date variant), one fixture with no articles, one fixture
  with malformed/truncated text (must return `[]`, not raise), one
  dedupe-across-blocks case.
- **Frontend (light, matching prior plans):** `SourcesPanel` renders
  entries when given data; renders nothing when given `[]`.
- **E2E:** no new E2E scenario required — this is additive data on an
  existing completed-run view already covered by
  `web/app/tests/e2e/search-to-result.spec.ts` et al. If those specs
  assert against the completed-run DOM shape, confirm the new panel
  doesn't break existing selectors; no new spec file needed for a
  read-only addition.

## Non-goals (explicitly out of scope here)

- Technical-indicator citations (RSI, MACD, Bollinger, ATR, SMA, etc.) —
  the user explicitly ruled these out for this iteration.
- Inline clickable citations inside report prose (turning the news
  analyst's `- [source, date]: highlight` Coverage bullets into live
  links) — deferred to `tradingagentsv2.md` as a v2 item; only the news
  analyst's Coverage section follows that citation convention today, and
  the bull/bear/debate stages don't, so full coverage would be partial or
  require a prompt change to those stages.
- Fundamentals, bull/bear case, risk-debate, and final-decision reports
  are not covered by this panel — user scope is "citations for news
  articles" only.

## Global constraints for the implementation plan

- No backend prompt or agent-pipeline change of any kind.
- No DB schema/migration change.
- `extract_news_sources` must never raise; empty list is the only failure
  mode visible to callers.
- `RunDetail.news_sources` is always a list (never `None`).
- `SourcesPanel` renders nothing (not a placeholder) when its input list
  is empty.
- Reuse the existing `.trace__*` CSS classes in `globals.css` — do not
  introduce parallel styling for the same visual pattern.
- Money-affecting API contract rules from prior plans remain binding
  everywhere else in the run response (unaffected by this change, but the
  implementer must not touch `Verdict`/`TradeLevels` handling while
  editing `api/schemas.py`).
