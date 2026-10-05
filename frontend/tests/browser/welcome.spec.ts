import { expect, test } from '@playwright/test';
import { suggestions } from '../../src/components/welcome/suggestions';

test('suggestions fill and focus the composer without making API requests', async ({ page }, testInfo) => {
  const apiRequests: string[] = [];
  page.on('request', (request) => { if (new URL(request.url()).pathname.startsWith('/api/')) apiRequests.push(request.url()); });
  await page.goto('/');
  const input = page.getByRole('textbox', { name: 'Your question' });
  const send = page.getByRole('button', { name: 'Send question' });
  await expect(send).toBeDisabled();
  for (const suggestion of suggestions) {
    await page.getByRole('button', { name: suggestion.label, exact: true }).click();
    await expect(input).toHaveValue(suggestion.question);
    await expect(input).toBeFocused();
    await expect(page.getByRole('status')).toContainText('Clears on refresh');
  }
  await page.screenshot({ path: testInfo.outputPath('welcome-draft.png'), fullPage: true, animations: 'disabled' });
  expect(apiRequests).toEqual([]);
});

test('Enter submits; Shift+Enter keeps multiline editing', async ({ page }) => {
  const messages: string[] = [];
  await page.route((url) => url.pathname.startsWith('/api/'), async (route) => {
    messages.push(route.request().postDataJSON().message);
    await route.fulfill({ json: { answer: 'Mocked answer.', citations: [], conversation_id: null } });
  });
  await page.goto('/');
  const input = page.getByRole('textbox');
  await input.fill('First line');
  await input.press('Shift+Enter');
  await input.press('S');
  await expect(input).toHaveValue('First line\nS');
  expect(messages).toEqual([]);
  await input.press('Enter');
  await expect(page.getByText('Mocked answer.', { exact: true })).toBeVisible();
  expect(messages).toEqual(['First line\nS']);
});

test('composer grows for multiline drafts, caps its height, and shrinks again', async ({ page }) => {
  await page.goto('/');
  const input = page.getByRole('textbox');
  const initialHeight = (await input.boundingBox())!.height;
  await input.fill(Array.from({ length: 12 }, (_, index) => `Line ${index}`).join('\n'));
  const expandedHeight = (await input.boundingBox())!.height;
  expect(expandedHeight).toBeGreaterThan(initialHeight);
  expect(expandedHeight).toBeLessThanOrEqual(190);
  await input.fill('');
  expect((await input.boundingBox())!.height).toBe(initialHeight);
});

test('navigation resets the draft and About traps and restores focus', async ({ page }, testInfo) => {
  await page.goto('/');
  const input = page.getByRole('textbox');
  const mobile = testInfo.project.name === 'mobile';
  await input.fill('A draft');
  if (mobile) {
    const trigger = page.getByRole('button', { name: 'Navigation menu' });
    await expect(page.getByRole('navigation', { name: 'Primary navigation' })).not.toBeVisible();
    await trigger.click();
    await expect(trigger).toHaveAttribute('aria-expanded', 'true');
    const nav = page.getByRole('navigation', { name: 'Mobile navigation' });
    await expect(nav.getByRole('button', { name: 'New chat' })).toBeFocused();
    await page.screenshot({ path: testInfo.outputPath('mobile-navigation.png'), fullPage: true, animations: 'disabled' });
    await nav.getByRole('button', { name: 'New chat' }).click();
    await expect(trigger).toHaveAttribute('aria-expanded', 'false');
  } else {
    await expect(page.getByRole('button', { name: 'Navigation menu' })).not.toBeVisible();
    await page.getByRole('button', { name: 'New chat' }).click();
  }
  await expect(input).toHaveValue('');
  await expect(input).toBeFocused();
  if (mobile) await page.getByRole('button', { name: 'Navigation menu' }).click();
  await page.getByRole('button', { name: 'About', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'About Pole Position' });
  const close = dialog.getByRole('button', { name: 'Close dialog' });
  await expect(dialog).toBeVisible();
  await expect(close).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(close).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await expect(close).toBeFocused();
  await page.screenshot({ path: testInfo.outputPath('about.png'), fullPage: true, animations: 'disabled' });
  await page.keyboard.press('Escape');
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole('button', { name: mobile ? 'Navigation menu' : 'About', exact: true })).toBeFocused();
  await input.fill('Another draft');
  await page.getByRole('button', { name: 'Go to welcome screen' }).click();
  await expect(input).toHaveValue('');
});

test('mobile menu dismisses with Escape and outside interaction', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  const trigger = page.getByRole('button', { name: 'Navigation menu' });
  await trigger.click();
  await page.keyboard.press('Escape');
  await expect(trigger).toHaveAttribute('aria-expanded', 'false');
  await expect(trigger).toBeFocused();
  await trigger.click();
  await page.getByRole('textbox').click();
  await expect(trigger).toHaveAttribute('aria-expanded', 'false');
  await expect(page.getByRole('textbox')).toBeFocused();
  await trigger.click();
  await page.setViewportSize({ width: 1000, height: 800 });
  await expect(page.getByRole('navigation', { name: 'Mobile navigation' })).toHaveCount(0);
});

test('welcome controls remain inside each viewport, including landscape', async ({ page }) => {
  for (const viewport of [
    { width: 320, height: 568 }, { width: 390, height: 844 },
    { width: 720, height: 900 }, { width: 768, height: 1024 },
    { width: 844, height: 390 }, { width: 1440, height: 1000 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto('/');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    for (const control of [page.getByRole('button', { name: 'Go to welcome screen' }),
      page.getByRole('textbox'), page.getByRole('button', { name: 'Send question' }),
      ...suggestions.map((suggestion) => page.getByRole('button', { name: suggestion.label, exact: true }))]) {
      const bounds = await control.boundingBox();
      expect(bounds!.x).toBeGreaterThanOrEqual(0);
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(viewport.width);
    }
  }
});
