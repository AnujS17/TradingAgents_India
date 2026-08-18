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
  // uppercase text.
  //
  // TheCall's ruler always renders all 5 tier labels (SELL/UNDERWEIGHT/
  // HOLD/OVERWEIGHT/BUY) regardless of the run's actual rating, so merely
  // finding "UNDERWEIGHT" text only proves a verdict card rendered with a
  // recognized rating, not that *this run's* rating is Underweight. The
  // active stop is the one distinguishing signal — TheCall.tsx applies
  // `text-[#00439D]` only to the span at `activeIndex`, no other class — so
  // assert that class to bind this back to the run's real data.
  const underweightStop = page.getByLabel('Verdict summary').getByText('UNDERWEIGHT', { exact: true });
  await expect(underweightStop).toBeVisible({ timeout: 15000 });
  await expect(underweightStop).toHaveClass(/00439D/);
  await expect(page.getByRole('status')).toHaveCount(0);
});
