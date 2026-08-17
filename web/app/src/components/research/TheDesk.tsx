// Ported from web/design/research/index.html lines 274-320 (sidebar "THE DESK").
//
// This is a fully static roster: the five teams and their agents never
// change run to run, so there is nothing here to fetch or compute. The API
// exposes only pipeline-level status (`RunDetail.status`), not per-agent
// progress — there is no endpoint that could tell us "Bull researcher is
// done but Bear researcher isn't". So the checkmarks below are decorative
// confirmation that the whole pipeline finished, not a live per-agent status
// feed. Rendering them at all is only honest once the run is complete.
//
// This component intentionally takes no props and does no gating of its
// own: like VerdictSummary/ReportsAccordion, the completed-status check
// lives once in the parent (RunView's existing
// `current.status === 'completed'` block) — TheDesk is meant to be mounted
// inside that same gate, not to duplicate the check.

const CHECK_MARK = (
  <svg width="9" height="9" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path d="M5 13l4 4L19 7" stroke="#fff" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

type Team = {
  name: string;
  count: number;
  href: string;
  agents: string[];
};

// Hrefs match the source markup verbatim (web/design/research/index.html
// lines 280/290/299/306/315). Analysts and Trader both point at `#record`
// in the source; kept as-is here since the actual section ids are assigned
// by Task 10/11 and should be verified against those at integration time.
const TEAMS: Team[] = [
  { name: 'Analysts', count: 4, href: '#record', agents: ['Market', 'Fundamentals', 'News', 'Sentiment'] },
  { name: 'Research', count: 3, href: '#disagree', agents: ['Bull researcher', 'Bear researcher', 'Research manager'] },
  { name: 'Trader', count: 1, href: '#record', agents: ['Trader'] },
  { name: 'Risk panel', count: 3, href: '#risk', agents: ['Aggressive', 'Neutral', 'Conservative'] },
  { name: 'Portfolio', count: 1, href: '#call', agents: ['Portfolio manager'] },
];

export function TheDesk() {
  return (
    <aside className="lg:sticky lg:top-24">
      <h2 className="font-tight font-extrabold text-[#010101] text-lg">The desk</h2>
      <p className="copy text-[#6F6F6F] mt-1 mb-6">Five teams. Each handed its work to the next.</p>

      {TEAMS.map((team) => (
        <div className="team" key={team.name}>
          <a className="team__link" href={team.href}>
            {team.name} <span className="team__n">{team.count}</span>
          </a>
          <div className="mt-2">
            {team.agents.map((agent) => (
              <div className="ag is-done" key={agent}>
                <span className="ag__mark">{CHECK_MARK}</span>
                <span className="ag__name">{agent}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </aside>
  );
}
