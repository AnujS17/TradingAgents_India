import { expect, test } from '@playwright/test';

test('a failed run shows its error plainly and does not spin', async ({ page }) => {
  await page.goto('/runs/run-failed');

  // Next.js's App Router mounts its own hidden accessibility announcer
  // (#__next-route-announcer__, inside an open shadow root) which also
  // carries role="alert". Excluding it by id keeps this scoped to the
  // app's own error alert regardless of hydration timing.
  const alert = page.locator('[role="alert"]:not(#__next-route-announcer__)');
  await expect(alert).toContainText('The market data provider timed out');
  await expect(page.getByRole('status')).toHaveCount(0);
});
