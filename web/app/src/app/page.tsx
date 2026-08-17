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
      <Hero />
      <TrustStrip />
      <PipelineStack />
      <UseCases />
      <Deck />
      <LiveSplitFeature />
      <Faq />
      <CtaSection />
      <RecentRunsSection runs={recentRuns} />
      <SiteFooter />
    </>
  );
}
