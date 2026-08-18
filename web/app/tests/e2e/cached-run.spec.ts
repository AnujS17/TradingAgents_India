import { expect, test } from '@playwright/test';

// POST /analyze answers 200 (existing run, free) or 202 (newly queued, costs
// money) with the same body shape, so the UI has to branch on the status code.
// This exercises the 200 branch against a real HTTP response rather than a
// unit-level mock.
test('an existing analysis comes back instantly and is marked cached', async ({ page }) => {
  await page.goto('/');
  // Scoped to #try (the hero's SearchForm wrapper) — see the comment in
  // search-to-result.spec.ts: the assembled page (Task 7) has a second,
  // visually identical "Start researching" button in CtaSection, so an
  // unscoped role query is ambiguous.
  const heroForm = page.locator('#try');
  await heroForm.getByLabel('Ticker symbol').fill('CACHED');
  await heroForm.getByRole('button', { name: 'Start researching' }).click();

  // Generous timeout: this is the first navigation of the suite, so the dev
  // server is compiling /runs/[id] on demand while the router waits on it.
  await expect(page).toHaveURL(/\/runs\/run-completed\?cached=1$/, { timeout: 20000 });

  // Straight to the verdict — no queued/running banner, because nothing was
  // queued. TheCall (Task 9) only ever prints the rating as an uppercase
  // ruler label (RATING_STOPS.map -> stop.toUpperCase()), never in its
  // original case — see the same note in search-to-result.spec.ts. All 5
  // tier labels always render regardless of the run's actual rating, so
  // also assert the highlighted-stop class (`text-[#00439D]`, applied only
  // at `activeIndex` in TheCall.tsx) to bind this back to the run's real
  // data, not just "a recognized rating rendered somewhere".
  const underweightStop = page.getByLabel('Verdict summary').getByText('UNDERWEIGHT', { exact: true });
  await expect(underweightStop).toBeVisible({ timeout: 15000 });
  await expect(underweightStop).toHaveClass(/00439D/);
  await expect(page.getByRole('status')).toHaveCount(0);
});
