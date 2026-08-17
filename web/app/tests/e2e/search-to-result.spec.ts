import { expect, test } from '@playwright/test';

test('search queues a run and shows the verdict once it completes', async ({ page }) => {
  await page.goto('/');
  // Scoped to #try (the hero's SearchForm wrapper, see Hero.tsx): the
  // assembled landing page (Task 7) also has a second "Start researching"
  // button in CtaSection, both showing identical visible button copy by
  // design (verbatim from the reference mockup in both places) — so an
  // unscoped getByRole('button', { name: 'Start researching' }) is a strict-
  // mode violation once the whole page is composed. This test exercises the
  // primary hero search flow, so it targets that form specifically.
  const heroForm = page.locator('#try');
  await heroForm.getByLabel('Ticker symbol').fill('PROGRESS');
  await heroForm.getByRole('button', { name: 'Start researching' }).click();

  await expect(page).toHaveURL(/\/runs\/run-progressive/);
  await expect(page.getByRole('status')).toContainText(/Queued|Running/);

  // Scoped to the Verdict summary section: the completed run's report prose
  // mentions "Underweight" many more times, which makes an unscoped
  // getByText('Underweight') ambiguous (strict-mode violation) once the
  // full page has rendered. The real TheCall card (Task 9, ported from
  // web/design/research/index.html) never prints the rating in its original
  // case — it only ever appears as an uppercase ruler label
  // (RATING_STOPS.map -> stop.toUpperCase()) — so this asserts against that
  // uppercase text instead of the old placeholder's case-preserved <dd>.
  await expect(
    page.getByLabel('Verdict summary').getByText('UNDERWEIGHT', { exact: true }),
  ).toBeVisible({ timeout: 15000 });
  await expect(page.getByRole('status')).toHaveCount(0);
});
