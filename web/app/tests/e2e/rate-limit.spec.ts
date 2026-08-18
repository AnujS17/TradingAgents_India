import { expect, test } from '@playwright/test';

test('a 429 shows the server message, and cached reads keep working', async ({ page }) => {
  await page.goto('/');
  // Scoped to #try (the hero's SearchForm wrapper) — see the comment in
  // search-to-result.spec.ts: the assembled page (Task 7) has a second,
  // visually identical "Start researching" button in CtaSection, so an
  // unscoped role query is ambiguous.
  const heroForm = page.locator('#try');
  await heroForm.getByLabel('Ticker symbol').fill('RATELIMIT');
  await heroForm.getByRole('button', { name: 'Start researching' }).click();

  // Next.js's App Router mounts its own hidden accessibility announcer
  // (#__next-route-announcer__, inside an open shadow root) which also
  // carries role="alert". Excluding it by id keeps this scoped to the
  // app's own error alert regardless of hydration timing.
  const alert = page.locator('[role="alert"]:not(#__next-route-announcer__)');
  await expect(alert).toContainText('limit of 10');
  await expect(alert).toContainText('Existing analyses are still available');

  // The mock server's /runs listing echoes each fixture's own internal `id`
  // field rather than the Map key it's stored under (see Task 10 review),
  // so the recent-runs link for the completed SIEMENS.NS run points at
  // /runs/<fixture-id>, not the literal /runs/run-completed. Assert against
  // the link's actual href instead of a hardcoded slug.
  const cachedRunLink = page.getByRole('link', { name: /SIEMENS.NS/ });
  const href = await cachedRunLink.getAttribute('href');
  await cachedRunLink.click();
  await expect(page).toHaveURL(new RegExp(`${href!.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`));
  // TheCall (Task 9) only ever prints the rating as an uppercase ruler label
  // (RATING_STOPS.map -> stop.toUpperCase()), never in its original case —
  // see the same note in search-to-result.spec.ts. All 5 tier labels always
  // render regardless of the run's actual rating, so also assert the
  // highlighted-stop class (`text-[#00439D]`, applied only at
  // `activeIndex` in TheCall.tsx) to bind this back to the run's real data,
  // not just "a recognized rating rendered somewhere".
  const underweightStop = page.getByLabel('Verdict summary').getByText('UNDERWEIGHT', { exact: true });
  await expect(underweightStop).toBeVisible();
  await expect(underweightStop).toHaveClass(/00439D/);
});
