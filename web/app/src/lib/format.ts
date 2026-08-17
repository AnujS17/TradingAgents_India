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
