import { describe, expect, it } from 'vitest';
import { formatPrice } from '@/lib/format';

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
