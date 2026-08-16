import { expect, test } from '@playwright/test';

test('search queues a run and shows the verdict once it completes', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Ticker (NSE/BSE)').fill('PROGRESS');
  await page.getByRole('button', { name: 'Analyse' }).click();

  await expect(page).toHaveURL(/\/runs\/run-progressive/);
  await expect(page.getByRole('status')).toContainText(/Queued|Running/);

  // Scoped to the Verdict summary section: the completed run's report prose
  // mentions "Underweight" many more times, which makes an unscoped
  // getByText('Underweight') ambiguous (strict-mode violation) once the
  // full page has rendered.
  await expect(
    page.getByLabel('Verdict summary').getByText('Underweight', { exact: true }),
  ).toBeVisible({ timeout: 15000 });
  await expect(page.getByRole('status')).toHaveCount(0);
});
