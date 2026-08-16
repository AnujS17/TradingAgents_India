import { expect, test } from '@playwright/test';

// POST /analyze answers 200 (existing run, free) or 202 (newly queued, costs
// money) with the same body shape, so the UI has to branch on the status code.
// This exercises the 200 branch against a real HTTP response rather than a
// unit-level mock.
test('an existing analysis comes back instantly and is marked cached', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Ticker (NSE/BSE)').fill('CACHED');
  await page.getByRole('button', { name: 'Analyse' }).click();

  // Generous timeout: this is the first navigation of the suite, so the dev
  // server is compiling /runs/[id] on demand while the router waits on it.
  await expect(page).toHaveURL(/\/runs\/run-completed\?cached=1$/, { timeout: 20000 });

  // Straight to the verdict — no queued/running banner, because nothing was
  // queued.
  await expect(
    page.getByLabel('Verdict summary').getByText('Underweight', { exact: true }),
  ).toBeVisible({ timeout: 15000 });
  await expect(page.getByRole('status')).toHaveCount(0);
});
