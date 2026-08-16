import type { RunHistory } from '@/lib/api-client/client';

export function RunHistoryPanel({ history }: { history: RunHistory | null }) {
  if (!history || history.run_count <= 1) return null;

  const counts = new Map<string, number>();
  for (const rating of history.ratings) {
    const key = rating ?? 'No rating';
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  const breakdown = Array.from(counts.entries())
    .map(([rating, count]) => `${count} said ${rating}`)
    .join(', ');

  return (
    <section aria-label="Run history">
      <p>
        Analysed {history.run_count} times — {breakdown}.
      </p>
      {history.verdict_is_contested && (
        <p>
          These runs disagreed. The day&apos;s data was identical, so a split
          rating means the evidence was genuinely balanced — not a bug.
        </p>
      )}
    </section>
  );
}
