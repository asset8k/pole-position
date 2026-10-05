import { expect, test } from '@playwright/test';

test('loads local fonts, renders without errors, and captures the visual system', async ({ page }, testInfo) => {
  const errors: string[] = [];
  const requests: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('request', (request) => requests.push(request.url()));
  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  const fonts = await page.evaluate(async () => {
    await document.fonts.ready;
    return {
      ui: document.fonts.check('500 16px "Hanken Grotesk"'),
      brand: document.fonts.check('600 25px "Barlow Condensed"'),
      loaded: [...document.fonts].filter((font) => font.status === 'loaded').map((font) => font.family),
    };
  });
  expect(fonts.ui).toBe(true);
  expect(fonts.brand).toBe(true);
  expect(fonts.loaded).toEqual(expect.arrayContaining(['Hanken Grotesk', 'Barlow Condensed']));
  expect(requests.some((url) => url.endsWith('/fonts/HankenGrotesk-Variable.ttf'))).toBe(true);
  expect(requests.some((url) => url.endsWith('/fonts/BarlowCondensed-SemiBold.woff2'))).toBe(true);
  expect(requests.every((url) => new URL(url).hostname === '127.0.0.1')).toBe(true);
  expect(errors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath('foundation.png'), fullPage: true, animations: 'disabled' });
});

test('keyboard focus is visible and the preview controls work without API calls', async ({ page }, testInfo) => {
  const apiRequests: string[] = [];
  page.on('request', (request) => { if (request.url().includes('/api/')) apiRequests.push(request.url()); });
  await page.goto('/');
  await page.keyboard.press('Tab');
  const input = page.getByRole('textbox', { name: 'Question preview' });
  await expect(input).toBeFocused();
  expect(await input.evaluate((element) => getComputedStyle(element).outlineStyle)).toBe('solid');
  await input.fill('How many tyre specifications?');
  await page.keyboard.press('Tab');
  const preview = page.getByRole('button', { name: 'Preview' });
  await expect(preview).toBeFocused();
  await page.screenshot({ path: testInfo.outputPath('controls-focus.png'), fullPage: true, animations: 'disabled' });
  await page.keyboard.press('Enter');
  await expect(page.getByRole('status')).toHaveText('Controls ready. Chat comes next.');
  await page.getByRole('button', { name: 'Reset' }).click();
  await expect(preview).toBeDisabled();
  expect(apiRequests).toEqual([]);
});

test('primary button text has sufficient contrast at rest and on hover', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');
  await page.getByRole('textbox').fill('A question');
  const button = page.getByRole('button', { name: 'Preview' });
  const contrast = async () => button.evaluate((element) => {
    const luminance = (color: string) => {
      const channels = color.match(/[\d.]+/g)!.slice(0, 3).map(Number)
        .map((value) => value / 255)
        .map((value) => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4);
      return channels[0] * .2126 + channels[1] * .7152 + channels[2] * .0722;
    };
    const style = getComputedStyle(element);
    const values = [luminance(style.color), luminance(style.backgroundColor)].sort((a, b) => b - a);
    return (values[0] + .05) / (values[1] + .05);
  });
  expect(await contrast()).toBeGreaterThanOrEqual(4.5);
  await button.hover();
  expect(await contrast()).toBeGreaterThanOrEqual(4.5);
});

test('fits narrow viewports and honors reduced motion', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  for (const width of [320, 390, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await expect(page.getByRole('textbox')).toBeVisible();
  }
  expect(await page.getByRole('button', { name: 'Reset' })
    .evaluate((element) => getComputedStyle(element).transitionDuration)).toBe('0s');
});
