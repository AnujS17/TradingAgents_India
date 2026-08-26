/**
 * The engine deliberately drops a level it can't make coherent rather than
 * emit a misleading number — a null here is a real answer, not missing data.
 * Rendering it as 0 would be a wrong statement, not a formatting nicety.
 */
export function formatPrice(value: number | null | undefined): string {
  if (value === null || value === undefined) return 'Not set';
  return `₹${value.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
}

/** Matches a trailing timezone designator: `Z`, `+05:30`, or `-0500`. */
const TIMEZONE_SUFFIX = /(?:Z|[+-]\d{2}:?\d{2})$/;

/**
 * The API serialises timestamps from naive Python datetimes, so they arrive
 * with no timezone designator (`"2026-08-12 14:26:16.574344"`). Per the JS
 * spec, `Date.parse` reads a date-time string without an offset as *local*
 * time, which silently shifts elapsed-time maths by the viewer's UTC offset
 * (+5:30 for an IST user, negative for the Americas). The backend stores UTC,
 * so append `Z` when — and only when — the string doesn't already carry an
 * offset of its own.
 */
export function parseApiTimestamp(value: string): number {
  const normalised = TIMEZONE_SUFFIX.test(value) ? value : `${value.trim().replace(' ', 'T')}Z`;
  return Date.parse(normalised);
}

/**
 * Formats a millisecond duration as `Xm Ys`. Shared by `RunStatusBanner`
 * (elapsed time while a run is in flight) and `RunHeader` (final run time of
 * a completed run) so the two surfaces can't drift into different rounding.
 */
export function formatDuration(ms: number): string {
  const totalSeconds = Math.max(0, Math.round(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}m ${seconds}s`;
}

/**
 * Word count for one report body. Reused by `RunHeader` (summed across all
 * non-null reports for the "Written" stat) and Task 10's `ReportsRecord`.
 */
export function countWords(text: string): number {
  return text.trim().split(/\s+/).filter(Boolean).length;
}

/**
 * 200wpm, rounded up, floor of 1 minute — the standard estimate (Medium,
 * Substack) applied to real word counts, never a separate invented number.
 */
export function readMinutes(words: number): number {
  return Math.max(1, Math.round(words / 200));
}

/** Matches "**Executive Summary**: ..." or "**Executive Summary:**", case
 * insensitive, up to the next blank line or the next bold heading. */
const EXECUTIVE_SUMMARY = /\*\*Executive Summary\*\*:?\s*([\s\S]+?)(?:\n\n|\n\*\*|$)/i;

/**
 * The four analyst reports (market/sentiment/news/fundamentals) open with
 * several KB of raw pre-fetched data — OHLCV tables, StockTwits dumps, full
 * article lists, balance-sheet rows — before the agent's own synthesis.
 * Every one of them ends that data with a heading of this exact shape
 * ("## Market Analyst Report", "## Sentiment Analyst Report", ...); the
 * agent's real narrative starts immediately after it. Verified against a
 * real completed run (HAL.NS, 2026-08-23) for all four report types before
 * relying on it — this is not a guessed pattern.
 */
const ANALYST_REPORT_MARKER = /^##\s+.*\bAnalyst Report\b\s*$/im;

/** Below this length a block is a label, not an excerpt — real examples
 * that must NOT win: "**Action**: Buy", "**Recommendation**: Overweight".
 * The real paragraph a reader wants (**Reasoning**: ..., **Rationale**: ...)
 * sits right after it and is long enough to clear this easily. */
const MIN_EXCERPT_CHARS = 50;

function isNoiseBlock(block: string): boolean {
  if (!block) return true;
  if (block.startsWith('#')) return true; // a heading, not prose
  if (block.startsWith('_') || block.startsWith('<')) return true; // italic meta-note / bracketed system note
  if (/^(Note|Link|Source)[:.]/i.test(block)) return true;
  if (/^\[\d{4}-\d{2}-\d{2}/.test(block)) return true; // a raw timestamped social post
  return stripMarkdown(block).length < MIN_EXCERPT_CHARS;
}

function stripMarkdown(source: string): string {
  return source
    .replace(/^#+\s*/gm, '')
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/\*(.+?)\*/g, '$1')
    .replace(/\s+/g, ' ')
    .trim();
}

/**
 * A short, human excerpt for a report's collapsed-row preview
 * (ReportsRecord.tsx). In order: the report's own **Executive Summary**
 * line when the agent wrote one (final_decision — this is literally the
 * sentence the reader is trying to see without expanding the row); the
 * first substantial paragraph after the "## X Analyst Report" marker for
 * the four data-heavy analyst reports (skips straight past their raw
 * pre-fetched data); otherwise the first substantial paragraph in the
 * report as a whole (investment_plan, trader_plan, bull_case, bear_case,
 * risk_debate — all open directly with real argument, no data preamble).
 * "Substantial" excludes headings, meta-notes, and short label:value lines
 * — see isNoiseBlock.
 *
 * Markdown-stripped, not markdown-rendered: this sits in plain row text,
 * not through ReactMarkdown, so bold/heading syntax must not leak through
 * as literal asterisks or hashes.
 */
export function excerptFor(markdown: string, maxLength = 200): string {
  const summaryMatch = markdown.match(EXECUTIVE_SUMMARY);
  let source: string;

  if (summaryMatch) {
    source = summaryMatch[1];
  } else {
    const marker = markdown.match(ANALYST_REPORT_MARKER);
    const searchZone = marker ? markdown.slice((marker.index ?? 0) + marker[0].length) : markdown;
    const blocks = searchZone.split(/\n{2,}/).map((block) => block.trim());
    source = blocks.find((block) => !isNoiseBlock(block)) ?? searchZone;
  }

  const plain = stripMarkdown(source);
  if (plain.length <= maxLength) return plain;
  return `${plain.slice(0, maxLength).replace(/\s+\S*$/, '')}…`;
}
