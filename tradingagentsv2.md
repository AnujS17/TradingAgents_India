# TradingAgents v2 — deferred ideas

Backlog of scoped-out or deferred feature ideas, kept here instead of a plan
or spec so they don't get lost. Not committed to a timeline.

## Inline clickable news citations (v2 of the news-sources feature)

**Origin:** while designing the evidence-trace / news-citation feature
(2026-08-19), the initial build ships a **Sources panel** — a list of every
article actually fetched for the News/Sentiment report, shown alongside it.

A v2 could go further: turn the `- [source, date]: <highlight>` bullets the
news analyst already writes in its `### Coverage` section
(`tradingagents/agents/analysts/news_analyst.py`) into **clickable inline
citations** — matched back to the specific article by `(source, date)` and
linking straight to that article's entry in the Sources panel, rather than
requiring the reader to scan the list.

**Why deferred:** this citation format is only reliably present in the news
analyst's Coverage bullets today. The bull/bear case and other debate-stage
prose don't follow a structured `(source, date)` citation convention, so
inline linking there would either be partial (only Coverage bullets get
live links, everything else doesn't) or require a prompt change to the
debate agents to adopt the same convention — a change to an already-tuned
multi-agent pipeline, with the reliability risk that entails (a wrong or
stale inline citation is worse than none — see `web/design/DESIGN.md`'s
evidence-trace section on reconciliation discipline).

**Possible shape when picked up:**
- Parse `- [source, date]: <highlight>` lines in `news_report`'s Coverage
  section client-side (or server-side at persistence time).
- Match `(source, date)` against the structured `news_sources` list the v1
  Sources panel already introduces.
- Render matched bullets with a link/anchor into the Sources panel instead
  of plain text; unmatched bullets render unchanged (graceful degradation,
  never a dead or wrong link).
- Only expand to bull_case/bear_case/other prose if/when those stages adopt
  a similarly structured citation convention — never guess a citation by
  fuzzy-matching free text.
