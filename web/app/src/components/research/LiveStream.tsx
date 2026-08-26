'use client';

import { useEffect, useRef, useState } from 'react';
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
  // Sticky-bottom auto-scroll: true means the reader was at (or within
  // 24px of) the bottom before this update, so the view follows the
  // newest token. A reader who scrolls up to re-read an earlier line flips
  // this to false and the view stops pulling them back down. Without this,
  // scrollTop = scrollHeight on every token permanently hides whatever the
  // reader scrolled up to look at -- and, worse, scrolls a report's own
  // heading out of view the instant more text arrives beneath it.
  const stickToBottomRef = useRef(true);
  const [hasOverflow, setHasOverflow] = useState(false);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const handleScroll = () => {
      stickToBottomRef.current = el.scrollTop + el.clientHeight >= el.scrollHeight - 24;
    };
    el.addEventListener('scroll', handleScroll, { passive: true });
    return () => el.removeEventListener('scroll', handleScroll);
  }, [hasSpoken]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    // has-overflow gates the read-cue mask in globals.css: a well that
    // isn't actually scrolling must never fade its own fully-visible text.
    setHasOverflow(el.scrollHeight > el.clientHeight + 1);
    if (stickToBottomRef.current) el.scrollTop = el.scrollHeight;
  }, [text]);

  return (
    <div className="mt-1">
      <div className={`ag ${hasSpoken ? 'is-live' : ''}`}>
        <span className="ag__mark" />
        <span className="ag__name">{name}</span>
      </div>
      {hasSpoken && (
        <div
          ref={scrollRef}
          className={`live__doc ml-7${hasOverflow ? ' has-overflow' : ''}`}
        >
          {/* Agents write real markdown mid-report (headers, bold, GFM
              tables -- see keeps_markdown_tables()), so rendering the raw
              streamed text through the same react-markdown/remark-gfm pair
              ReportsRecord already uses turns it from one unbroken run-on
              paragraph into actual structure, programmatically -- no
              prompt change. remark-gfm degrades incomplete syntax (an
              unclosed ** or a half-written table row) to plain text rather
              than erroring, so this is safe on a value that grows one
              token at a time. */}
          {/* del: 'span' -- see ReportsRecord.tsx's identical override: a
              reasoning model occasionally leaks self-revision markup
              (~~old~~ new) into a field, which GFM renders as a literal
              struck-through line rather than the plain prose it should be. */}
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ del: 'span' }}>
            {text}
          </ReactMarkdown>
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

      {/* items-start: a CSS grid row stretches every cell to match its
          tallest sibling by default, which left idle "Waiting" teams as
          mostly-empty cards trailing far below their own three lines of
          content whenever a neighbouring team's streamed text ran long. */}
      <div className="mt-6 grid gap-5 sm:grid-cols-2 xl:grid-cols-3 items-start">
        {TEAMS.map((team) => {
          const isActive = team.agents.some((agent) => eventsByNode[agent]);

          return (
            <div key={team.name} className={`live__team ${isActive ? 'is-active' : ''}`}>
              <div className="flex items-center justify-between gap-3">
                {/* 17px/700, not the row-label 15px: this is a card title
                    (DESIGN.md's type ramp), the same role as ReportsRecord's
                    .rep__t or a stack-card's heading, not a list link like
                    TheDesk's .team__link, which is where 15px belongs. */}
                <p className="font-tight font-bold text-[17px] text-[#010101]">{team.name}</p>
                <span
                  className={
                    isActive
                      ? 'font-tight font-bold text-xs rounded-full bg-[#F0F6FF] text-[#00439D] border border-[#D3E1F7] px-3 py-1'
                      : 'font-tight font-bold text-xs rounded-full bg-[#F5F6F8] text-[#676D80] border border-[#E4E6EB] px-3 py-1'
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
