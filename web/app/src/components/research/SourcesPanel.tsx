import type { NewsSource } from '@/lib/api-client/client';

// Real citations for the News/Sentiment reports, not a drill-down: every
// entry is an article those reports were actually grounded in (see
// docs/superpowers/specs/2026-08-19-news-sources-design.md). Renders
// nothing when empty, matching RunHistoryPanel's null-render pattern —
// an empty citation list is a legitimate state, never a placeholder.
export function SourcesPanel({ sources }: { sources: NewsSource[] }) {
  if (sources.length === 0) return null;

  return (
    <section aria-label="News sources" className="mt-8 rounded-[28px] border border-[#E0E1E2] bg-white p-7 lg:p-9">
      <h2 className="font-tight font-black text-[#010101] text-2xl tracking-[-0.02em]">Sources</h2>
      <p className="copy text-[#6F6F6F] mt-1 measure">
        Every article the News and Sentiment reports above were actually given.
      </p>

      <div className="mt-4 grid gap-3">
        {sources.map((item, index) => (
          <div className="trace__in" key={`${item.source}-${item.title}-${index}`}>
            <p className="trace__src">{item.source}</p>
            <p className="trace__k">
              {item.url ? (
                <a href={item.url} target="_blank" rel="noreferrer">
                  {item.title}
                </a>
              ) : (
                item.title
              )}
            </p>
            {(item.published_date || item.snippet) && (
              <p className="trace__note">
                {item.published_date ? `${item.published_date} — ` : ''}
                {item.snippet}
              </p>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
