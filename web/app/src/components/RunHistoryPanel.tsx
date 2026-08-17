import Link from 'next/link';
import type { RunHistory } from '@/lib/api-client/client';

/**
 * `runCount`/`isContested` come from the RunDetail the page already has, so a
 * contested verdict is stated even when the enriched history request is still
 * in flight, errors, or 404s — hiding it behind a secondary query would let a
 * genuinely split verdict read as unanimous. `history` only adds detail on
 * top: the per-rating breakdown and links to the individual runs.
 */
export function RunHistoryPanel({
  runCount,
  isContested,
  history = null,
  isError = false,
}: {
  runCount: number;
  isContested: boolean;
  history?: RunHistory | null;
  isError?: boolean;
}) {
  const count = history?.run_count ?? runCount;
  const contested = history?.verdict_is_contested ?? isContested;

  // A single run can't disagree with itself — silence is the right answer.
  if (count <= 1) return null;

  const counts = new Map<string, number>();
  for (const rating of history?.ratings ?? []) {
    const key = rating ?? 'No rating';
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  const breakdown = Array.from(counts.entries())
    .map(([rating, ratingCount]) => `${ratingCount} said ${rating}`)
    .join(', ');

  // `ratings` holds one entry per *completed* sibling while `runs` holds every
  // sibling (api/store.py `_ratings`), so the two lists only line up when no
  // run is queued, running, or failed. Walk them with a separate counter
  // instead of indexing `ratings` by the run's position.
  let completedSoFar = 0;
  const runLinks = (history?.runs ?? []).map((run) => ({
    run,
    label:
      run.status === 'completed'
        ? history?.ratings[completedSoFar++] ?? 'No rating'
        : `Not completed (${run.status})`,
  }));

  return (
    <section
      aria-label="Run history"
      className="mt-8 rounded-[28px] border border-[#E0E1E2] bg-white p-7 lg:p-9"
    >
      <h2 className="font-tight font-black text-[#010101] text-2xl tracking-[-0.02em]">Run history</h2>
      <p className="copy text-[#6F6F6F] mt-1 measure">
        Analysed {count} times{breakdown ? ` — ${breakdown}` : ''}.
      </p>
      {contested && (
        <p className="copy font-semibold text-[#1C6FE6] mt-4 measure">
          These runs disagreed. The day&apos;s data was identical, so a split
          rating means the evidence was genuinely balanced — not a bug.
        </p>
      )}
      {isError && (
        <p className="copy text-[#676D80] mt-4">
          Couldn&apos;t load run history — the per-run breakdown and links aren&apos;t available.
        </p>
      )}
      {runLinks.length > 0 && (
        <ul className="mt-6 grid gap-px bg-[#EBEBEB] rounded-2xl overflow-hidden">
          {runLinks.map(({ run, label }) => (
            <li key={run.id} className="bg-white">
              {/* created_at is ISO-like in both the naive and offset forms the
                  API emits, so the first 10 characters are its calendar date. */}
              <Link
                href={`/runs/${run.id}`}
                className="block px-4 py-3.5 font-tight font-semibold text-sm text-[#010101] tabular-nums transition hover:text-[#1C6FE6]"
              >
                {label} — {run.created_at.slice(0, 10)}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
