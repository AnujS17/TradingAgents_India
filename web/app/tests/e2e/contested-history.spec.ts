import { expect, test } from '@playwright/test';

test('a contested verdict is surfaced, not hidden behind the latest rating', async ({ page }) => {
  await page.goto('/runs/run-completed');

  await expect(page.getByText(/Analysed 3 times/)).toBeVisible();
  await expect(page.getByText(/disagreed/)).toBeVisible();

  // Being told the runs disagreed is useless without a way to read the
  // dissenting one, so each sibling run links to its own page.
  await expect(page.getByRole('link', { name: /Hold — 2026-08-14/ })).toHaveAttribute(
    'href',
    '/runs/run-3',
  );
});
