import { expect, test } from '@playwright/test';

test('a 429 shows the server message, and cached reads keep working', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Ticker (NSE/BSE)').fill('RATELIMIT');
  await page.getByRole('button', { name: 'Analyse' }).click();

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
  await expect(page.getByLabel('Verdict summary').getByText('Underweight', { exact: true })).toBeVisible();
});
