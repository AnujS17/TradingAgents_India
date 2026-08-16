import { describe, expect, it } from 'vitest';
import { formatPrice, parseApiTimestamp } from '@/lib/format';

describe('formatPrice', () => {
  it('renders null as "Not set", never 0', () => {
    expect(formatPrice(null)).toBe('Not set');
  });

  it('renders undefined as "Not set"', () => {
    expect(formatPrice(undefined)).toBe('Not set');
  });

  it('renders an actual zero price as ₹0, not "Not set"', () => {
    expect(formatPrice(0)).toBe('₹0');
  });

  it('formats a decimal price with the rupee sign', () => {
    expect(formatPrice(1234.5)).toBe('₹1,234.5');
  });
});

describe('parseApiTimestamp', () => {
  it('reads an offset-less API timestamp as UTC, not local time', () => {
    // Real shape from the API (naive Python datetime, no offset). Without the
    // appended Z this parses as local time, so a non-UTC viewer's elapsed
    // clock is wrong by their whole UTC offset.
    expect(parseApiTimestamp('2026-08-12 14:26:16.574344')).toBe(
      Date.UTC(2026, 7, 12, 14, 26, 16, 574),
    );
  });

  it('reads an offset-less ISO timestamp as UTC', () => {
    expect(parseApiTimestamp('2026-08-12T14:26:16')).toBe(Date.UTC(2026, 7, 12, 14, 26, 16));
  });

  it('leaves a Z-suffixed timestamp alone', () => {
    expect(parseApiTimestamp('2026-08-12T14:26:16Z')).toBe(Date.UTC(2026, 7, 12, 14, 26, 16));
  });

  it('respects an explicit offset instead of appending Z to it', () => {
    // 14:26 at +05:30 is 08:56 UTC — a double-append would either fail to
    // parse or silently drop the offset.
    expect(parseApiTimestamp('2026-08-12T14:26:16+05:30')).toBe(
      Date.UTC(2026, 7, 12, 8, 56, 16),
    );
  });

  it('respects an offset written without a colon', () => {
    expect(parseApiTimestamp('2026-08-12T14:26:16-0500')).toBe(
      Date.UTC(2026, 7, 12, 19, 26, 16),
    );
  });
});
