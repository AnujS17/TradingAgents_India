import { listRuns } from '@/lib/api-client/client';
import { SiteNav } from '@/components/landing/SiteNav';
import { TickerMarquee } from '@/components/landing/TickerMarquee';
import { Hero } from '@/components/landing/Hero';
import { TrustStrip } from '@/components/landing/TrustStrip';
import { PipelineStack } from '@/components/landing/PipelineStack';
import { UseCases } from '@/components/landing/UseCases';
import { Deck } from '@/components/landing/Deck';
import { LiveSplitFeature } from '@/components/landing/LiveSplitFeature';
import { Faq } from '@/components/landing/Faq';
import { CtaSection } from '@/components/landing/CtaSection';
import { RecentRunsSection } from '@/components/landing/RecentRunsSection';
import { SiteFooter } from '@/components/landing/SiteFooter';

export default async function HomePage() {
  const recentRuns = await listRuns({ limit: 10 });

  return (
    <>
      <SiteNav />
      <TickerMarquee />
      {/* The design source has no <main> (it's a static mockup, not a real
          app shell) — but every other route in this app has one
          (runs/[id]/page.tsx, stock/[ticker]/[date]/page.tsx, not-found.tsx,
          error.tsx), so its absence here was a port regression, not
          faithfulness to the reference. SiteNav/TickerMarquee (chrome, not
          page content) and SiteFooter stay outside it, matching the header/
          main/footer landmark split those other routes use. */}
      <main>
        <Hero />
        <TrustStrip />
        <PipelineStack />
        <UseCases />
        <Deck />
        <LiveSplitFeature />
        <Faq />
        <CtaSection />
        <RecentRunsSection runs={recentRuns} />
      </main>
      <SiteFooter />
    </>
  );
}
