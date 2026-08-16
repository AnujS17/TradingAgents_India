/**
 * The engine deliberately drops a level it can't make coherent rather than
 * emit a misleading number — a null here is a real answer, not missing data.
 * Rendering it as 0 would be a wrong statement, not a formatting nicety.
 */
export function formatPrice(value: number | null | undefined): string {
  if (value === null || value === undefined) return 'Not set';
  return `₹${value.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
}
