import type { NewsSource } from '@/lib/api-client/client';

// Real citations for the News/Sentiment reports, not a drill-down: every
// entry is an article those reports were actually grounded in (see
// docs/superpowers/specs/2026-08-19-news-sources-design.md). Renders
// nothing when empty — an empty citation list is a legitimate state,
// never a placeholder.
//
// 2026-08-23 rework: a tinted card per source (design review) read as
// heavy for what's fundamentally a link list — and left a dangling em dash
// on every row that had no snippet (`published_date + ' — ' + snippet`,
// snippet empty on every real source seen so far). Dropped the card, the
// snippet, and the separate uppercase source-label line; each source is
// now one dense row: the headline as the link, source and date as small
// trailing meta on the same line. Source and date are still real citation
// data, kept, just no longer given their own visual weight.
export function SourcesPanel({ sources }: { sources: NewsSource[] }) {
  if (sources.length === 0) return null;

  return (
    <section aria-label="News sources" className="mt-8 rounded-[28px] border border-[#E0E1E2] bg-white p-7 lg:p-9">
      <h2 className="font-tight font-black text-[#010101] text-2xl tracking-[-0.02em]">Sources</h2>
      <p className="copy text-[#6F6F6F] mt-1 measure">
        Every company-specific article the News and Sentiment reports above were actually given. Market-wide/macro context the analysis also used is not listed here.
      </p>

      <ul className="source-list mt-4">
        {sources.map((item, index) => (
          <li className="source-row" key={`${item.source}-${item.title}-${index}`}>
            {item.url ? (
              <a href={item.url} target="_blank" rel="noreferrer" className="source-row__link">
                {item.title}
              </a>
            ) : (
              <span className="source-row__link source-row__link--static">{item.title}</span>
            )}
            <span className="source-row__meta">
              {item.source}
              {item.published_date ? ` · ${item.published_date}` : ''}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
