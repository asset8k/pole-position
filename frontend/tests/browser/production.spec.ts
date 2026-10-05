import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { citation } from '../../src/test/citations';

test('built assets, local fonts, guest follow-up and citations work without the dev server', async ({ page }, info) => {
  const failed: string[] = [];
  const errors: string[] = [];
  const bodies: unknown[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('response', (response) => { if (response.status() >= 400) failed.push(response.url()); });
  await page.route((url) => url.pathname.startsWith('/api/'), async (route) => {
    expect(new URL(route.request().url()).pathname).toBe('/api/chat');
    bodies.push(route.request().postDataJSON());
    await route.fulfill({ json: { answer: 'Use two dry specifications. [S1]', citations: [citation()], conversation_id: null } });
  });
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Know the rules.' })).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  expect(await page.evaluate(() => document.fonts.check('16px "Hanken Grotesk"') && document.fonts.check('25px "Barlow Condensed"'))).toBe(true);
  expect(await page.evaluate(() => [...document.fonts].filter((font) => font.status === 'loaded').map((font) => font.family)))
    .toEqual(expect.arrayContaining(['Hanken Grotesk', 'Barlow Condensed']));
  for (const question of ['Tyre requirement?', 'What if they fail?']) {
    await page.getByRole('textbox', { name: 'Your question' }).fill(question);
    await page.getByRole('button', { name: 'Send question' }).click();
    await expect(page.locator('.chat-loading')).toHaveCount(0);
    await expect(page.getByRole('log')).toContainText('Use two dry specifications.');
  }
  expect(bodies).toEqual([
    { message: 'Tyre requirement?', history: [] },
    { message: 'What if they fail?', history: [{ role: 'user', content: 'Tyre requirement?' }, { role: 'assistant', content: 'Use two dry specifications. [S1]' }] },
  ]);
  await page.getByRole('group', { name: 'Sources' }).last().getByRole('button').click();
  await expect(page.getByRole('dialog', { name: 'Source S1' })).toContainText('PDF page 58');
  await page.evaluate(async () => {
    await Promise.all(document.getAnimations().filter((animation) => animation.effect?.getComputedTiming().iterations !== Infinity)
      .map((animation) => animation.finished.catch(() => undefined)));
  });
  const result = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze();
  expect(result.violations).toEqual([]);
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog', { name: 'Source S1' })).toHaveCount(0);
  expect(await page.evaluate(() => [...document.scripts].map((script) => script.src).filter(Boolean).every((src) => new URL(src).pathname.startsWith('/assets/')))).toBe(true);
  expect(failed).toEqual([]);
  expect(errors).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath('production-chat.png'), fullPage: true, animations: 'disabled' });
  await page.reload();
  await expect(page.getByRole('log')).toHaveCount(0);
});
