import { expect, test } from '@playwright/test';

test('a contested verdict is surfaced, not hidden behind the latest rating', async ({ page }) => {
  await page.goto('/runs/run-completed');

  await expect(page.getByText(/Analysed 3 times/)).toBeVisible();
  await expect(page.getByText(/disagreed/)).toBeVisible();
});
