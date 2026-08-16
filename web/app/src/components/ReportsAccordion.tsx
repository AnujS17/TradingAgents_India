'use client';

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Reports } from '@/lib/api-client/client';

const REPORT_LABELS: Record<keyof Reports, string> = {
  market: 'Market Analysis',
  sentiment: 'Sentiment Analysis',
  news: 'News Analysis',
  fundamentals: 'Fundamentals Analysis',
  bull_case: 'Bull Case',
  bear_case: 'Bear Case',
  investment_plan: 'Investment Plan',
  trader_plan: 'Trader Plan',
  risk_debate: 'Risk Debate',
  final_decision: 'Final Decision',
};

// Conclusion first, then evidence — final_decision opens by default so a
// reader sees a landing summary without needing to expand ten sections.
const REPORT_ORDER: (keyof Reports)[] = [
  'final_decision',
  'investment_plan',
  'bull_case',
  'bear_case',
  'trader_plan',
  'risk_debate',
  'market',
  'sentiment',
  'news',
  'fundamentals',
];

export function ReportsAccordion({ reports }: { reports: Reports | null }) {
  if (!reports) return null;

  const sections = REPORT_ORDER.filter((key) => reports[key]);
  if (sections.length === 0) return null;

  return (
    <section aria-label="Analyst reports">
      {sections.map((key, index) => (
        <details key={key} open={index === 0}>
          <summary>{REPORT_LABELS[key]}</summary>
          <div>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{reports[key] as string}</ReactMarkdown>
          </div>
        </details>
      ))}
    </section>
  );
}
