import { listRuns } from '@/lib/api-client/client';
import { RecentRuns } from '@/components/RecentRuns';
import { SearchForm } from '@/components/SearchForm';

export default async function HomePage() {
  const recentRuns = await listRuns({ limit: 10 });

  return (
    <main>
      <h1>TradingAgents — Indian Equity Research</h1>
      <p>
        Research, not advice. Every analysis returns full evidence — the bull
        case, the bear case, and the numbers — not just a rating.
      </p>
      <SearchForm />
      <RecentRuns runs={recentRuns} />
    </main>
  );
}
