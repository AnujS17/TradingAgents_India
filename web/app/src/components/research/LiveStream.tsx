'use client';

import { useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

// Team roster mirrors TheDesk.tsx's TEAMS exactly (same five teams, same
// grouping) -- the live view and the completed-run "desk" sidebar describe
// the same pipeline, so they must agree. Node names are the exact LangGraph
// node names this graph registers (tradingagents/graph/setup.py) -- these
// are the literal keys `eventsByNode` is populated with, not display labels.
const TEAMS: { name: string; agents: string[] }[] = [
  { name: 'Analysts', agents: ['Market Analyst', 'Fundamentals Analyst', 'News Analyst', 'Sentiment Analyst'] },
  { name: 'Research', agents: ['Bull Researcher', 'Bear Researcher', 'Research Manager'] },
  { name: 'Trader', agents: ['Trader'] },
  { name: 'Risk panel', agents: ['Aggressive Analyst', 'Neutral Analyst', 'Conservative Analyst'] },
  { name: 'Portfolio', agents: ['Portfolio Manager'] },
];

// "Speaking" is honest, not "done": there is no node-completion signal in
// the event stream yet (only token deltas), so an agent with content here
// has said something, not necessarily finished. Do not upgrade this to a
// done/checkmark state without a real completion signal behind it.
function AgentRow({ name, text }: { name: string; text: string | undefined }) {
  const hasSpoken = Boolean(text);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [text]);

  return (
    <div className="mt-1">
      <div className={`ag ${hasSpoken ? 'is-live' : ''}`}>
        <span className="ag__mark" />
        <span className="ag__name">{name}</span>
      </div>
      {hasSpoken && (
        <div ref={scrollRef} className="live__doc ml-7">
          {/* Agents write real markdown mid-report (headers, bold, GFM
              tables -- see keeps_markdown_tables()), so rendering the raw
              streamed text through the same react-markdown/remark-gfm pair
              ReportsRecord already uses turns it from one unbroken run-on
              paragraph into actual structure, programmatically -- no
              prompt change. remark-gfm degrades incomplete syntax (an
              unclosed ** or a half-written table row) to plain text rather
              than erroring, so this is safe on a value that grows one
              token at a time. */}
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
        </div>
      )}
    </div>
  );
}

// Live view while a run is in progress -- one card per team (same roster
// as TheDesk's completed-run sidebar), each agent's streamed text
// appearing under its own row as it arrives. Renders nothing until the
// first token of the run has actually arrived: before that (e.g. a run
// still `queued`) there is nothing true to show yet, and an empty shell
// of five idle cards would be a placeholder pretending to be a status.
export function LiveStream({ eventsByNode }: { eventsByNode: Record<string, string> }) {
  if (Object.keys(eventsByNode).length === 0) return null;

  return (
    <section aria-label="Live analysis" className="mt-8">
      <h2 className="font-tight font-black text-[#010101] text-2xl tracking-[-0.02em]">Live</h2>
      <p className="copy text-[#6F6F6F] mt-1 measure">Each team&rsquo;s work, as it&rsquo;s written.</p>

      <div className="mt-6 grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
        {TEAMS.map((team) => {
          const isActive = team.agents.some((agent) => eventsByNode[agent]);

          return (
            <div key={team.name} className="rounded-[28px] border border-[#E0E1E2] bg-white p-6">
              <div className="flex items-center justify-between gap-3">
                <p className="font-tight font-bold text-[15px] text-[#010101]">{team.name}</p>
                <span
                  className={
                    isActive
                      ? 'font-tight font-bold text-xs rounded-full bg-[#F0F6FF] text-[#00439D] border border-[#D3E1F7] px-3 py-1'
                      : 'font-tight font-bold text-xs rounded-full bg-[#F5F6F8] text-[#8A90A0] border border-[#E4E6EB] px-3 py-1'
                  }
                >
                  {isActive ? 'Speaking' : 'Waiting'}
                </span>
              </div>

              <div className="mt-3">
                {team.agents.map((agent) => (
                  <AgentRow key={agent} name={agent} text={eventsByNode[agent]} />
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
