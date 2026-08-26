/**
 * Rating and action color scale. This is a deliberate, scoped exception to
 * DESIGN.md §1's "green/red are reserved for price direction only" rule,
 * made 2026-08-23 (see DESIGN.md changelog note in the same commit): the
 * 5-tier rating (Sell..Buy) and the 3-tier action (Sell/Hold/Buy) now get
 * a real diverging color scale. Nothing else changes — bull/bear debate
 * framing stays on the existing navy/#1B6FA8 pair (that's an argument
 * stance, not a price-direction call, and the exception request was
 * specifically about the rating and action fields).
 *
 * Underweight and Overweight get their own, less saturated stops rather
 * than reusing Sell/Buy's colors at reduced opacity: they are genuinely
 * different positions on the 5-tier scale (trim vs exit, add vs full
 * conviction), and collapsing them visually to "a lighter version of Sell/
 * Buy" would blur a distinction the product is built to keep sharp (a Hold
 * action under an Underweight rating means "trim, don't exit" — see
 * TheCall.tsx / DEV_HANDOFF.md).
 */

export interface RatingColor {
  text: string;
  bg: string;
  border: string;
  /** 'down' | 'flat' | 'up' — shape-coded direction, independent of color,
   * so the rating still reads under prefers-contrast / grayscale / a
   * color-vision deficiency (WCAG 1.4.1, "use of color" is never the only
   * cue on this page). */
  direction: 'down' | 'flat' | 'up';
}

// Text colors are one Tailwind step darker than the visually "obvious" pick
// (red-700/orange-700/lime-700/green-700, not the -600 family) — verified in
// browser against a real run: the -600 shades measured 2.98-4.41:1 on their
// own tint background, real WCAG AA failures at the sizes these render at
// (the ruler labels are 11px; the ACTION value is 18px bold, which misses
// the 18.66px large-text threshold and still needs 4.5:1). The -700 family
// clears 4.5:1 on both white and each color's own tint.
const SCALE: Record<string, RatingColor> = {
  sell: { text: '#B91C1C', bg: '#FEF2F2', border: '#FECACA', direction: 'down' },
  underweight: { text: '#C2410C', bg: '#FFF7ED', border: '#FED7AA', direction: 'down' },
  hold: { text: '#676D80', bg: '#F4F6FB', border: '#E0E1E2', direction: 'flat' },
  overweight: { text: '#4D7C0F', bg: '#F7FEE7', border: '#D9F99D', direction: 'up' },
  buy: { text: '#15803D', bg: '#F0FDF4', border: '#BBF7D0', direction: 'up' },
};

const FALLBACK: RatingColor = { text: '#676D80', bg: '#F4F6FB', border: '#E0E1E2', direction: 'flat' };

/** Case-insensitive; an unrecognised label (or null) gets the neutral Hold
 * treatment rather than guessing, matching TheCall.tsx's existing "never
 * fabricate a rating position" discipline. */
export function ratingColor(label: string | null | undefined): RatingColor {
  if (!label) return FALLBACK;
  return SCALE[label.toLowerCase()] ?? FALLBACK;
}

export function DirectionArrow({ direction, className }: { direction: RatingColor['direction']; className?: string }) {
  if (direction === 'up') {
    return (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true" className={className}>
        <path d="M6 17L17 6M17 6H9M17 6V14" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  if (direction === 'down') {
    return (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true" className={className}>
        <path d="M6 7L17 18M17 18H9M17 18V10" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true" className={className}>
      <path d="M5 12h14" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" />
    </svg>
  );
}
