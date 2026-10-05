import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import { citation } from '../../src/test/citations';

async function mockChat(page: Page) {
  await page.route((url) => url.pathname.startsWith('/api/'), (route) => route.fulfill({ json: {
    answer: 'Use two different dry-weather tyre specifications. [S1]', citations: [citation()], conversation_id: null,
  } }));
}

test('screen navigation animates without replaying on typing or keeping old conversations', async ({ page }) => {
  await mockChat(page);
  await page.goto('/');
  const main = page.locator('main');
  // Record starts, including short-lived animations that finish before an assertion.
  await page.evaluate(() => {
    const original = Element.prototype.animate;
    Object.assign(window, { screenMotions: 0 });
    Element.prototype.animate = function (...args) {
      if (this.tagName === 'MAIN') (window as unknown as { screenMotions: number }).screenMotions++;
      return original.apply(this, args);
    };
  });
  const input = page.getByRole('textbox', { name: 'Your question' });
  await input.fill('Tyre changes?');
  expect(await page.evaluate(() => (window as unknown as { screenMotions: number }).screenMotions)).toBe(0);
  await page.getByRole('button', { name: 'Send question' }).click();
  await expect(main).toHaveAttribute('data-screen', 'chat:new');
  await expect(page.getByRole('group', { name: 'Sources' })).toBeVisible();
  await page.getByRole('button', { name: 'Go to welcome screen' }).click();
  await expect(main).toHaveAttribute('data-screen', 'welcome');
  await expect(input).toBeFocused();
  await expect(page.getByRole('log')).toHaveCount(0);
  expect(await page.evaluate(() => (window as unknown as { screenMotions: number }).screenMotions)).toBe(2);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('a dialog can reopen after its exit animation with working focus and controls', async ({ page }) => {
  await page.goto('/');
  for (let attempt = 0; attempt < 2; attempt++) {
    const menu = page.getByRole('button', { name: 'Navigation menu' });
    if (await menu.isVisible()) await menu.click();
    await page.getByRole('button', { name: 'About', exact: true }).click();
    const dialog = page.getByRole('dialog');
    const close = dialog.getByRole('button', { name: 'Close dialog' });
    await expect(close).toBeFocused();
    await expect(dialog.locator('.dialog__content')).not.toHaveAttribute('inert', '');
    await close.click();
    await expect(dialog).not.toBeVisible();
  }
});

test('source library link is visible for long excerpts, opens a safe new tab, and preserves the chat', async ({ page }, info) => {
  const excerpt = 'Original regulation text. '.repeat(400);
  await page.route((url) => url.pathname.startsWith('/api/'), (route) => route.fulfill({ json: {
    answer: 'Tyre rules [S1]', citations: [citation({ snippet: excerpt })], conversation_id: null,
  } }));
  await page.goto('/');
  await page.getByRole('textbox').fill('Tyres?');
  await page.getByRole('button', { name: 'Send question' }).click();
  const trigger = page.locator('.answer-content').getByRole('button', { name: /View source S1/ });
  await trigger.click();
  const drawer = page.getByRole('dialog');
  const link = drawer.getByRole('link', { name: /Full regulations.*opens in a new tab/ });
  await expect(link).toBeInViewport();
  await expect(link).toHaveAttribute('href', 'https://www.fia.com/regulation/category/110');
  await expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  await link.focus();
  await page.keyboard.press('Tab');
  await expect(drawer.getByRole('button', { name: 'Close source' })).toBeFocused();
  // Never contact the external site in a mocked browser test.
  await page.context().route('https://www.fia.com/**', (route) => route.fulfill({ contentType: 'text/html', body: '<title>FIA regulations</title>' }));
  const popupPromise = page.waitForEvent('popup');
  await link.click();
  const popup = await popupPromise;
  await popup.waitForLoadState('domcontentloaded');
  expect(popup.url()).toBe('https://www.fia.com/regulation/category/110');
  expect(await popup.evaluate(() => window.opener === null)).toBe(true);
  await popup.close();
  await expect(drawer.locator('.source-excerpt p')).toHaveText(excerpt.trim());
  await page.screenshot({ path: info.outputPath('source-library.png'), animations: 'disabled' });
  await page.keyboard.press('Escape');
  await expect(drawer).toHaveCount(0);
  await expect(trigger).toBeFocused();
  await expect(page.getByRole('log')).toContainText('Tyres?');
});

test('account hover uses a rounded surface and the menu closes accessibly', async ({ page }, info) => {
  await page.addInitScript(() => sessionStorage.setItem('pole-position:access-token', 'test-token'));
  await page.route('**/api/auth/me', (route) => route.fulfill({ json: { id: 1, username: 'assetk', created_at: '2026-10-05T12:00:00Z' } }));
  await page.route('**/api/conversations', (route) => route.fulfill({ json: [] }));
  await page.goto('/');
  const trigger = page.getByRole('button', { name: 'Account: assetk' });
  await trigger.click();
  const signOut = page.getByRole('button', { name: 'Sign out' });
  await expect(signOut).toBeFocused();
  expect(await signOut.evaluate((element) => getComputedStyle(element).borderRadius)).toBe('999px');
  const background = await signOut.evaluate((element) => getComputedStyle(element).backgroundColor);
  await signOut.hover();
  await expect.poll(() => signOut.evaluate((element) => getComputedStyle(element).backgroundColor)).not.toBe(background);
  await page.screenshot({ path: info.outputPath('rounded-sign-out.png'), animations: 'disabled' });
  await page.keyboard.press('Escape');
  await expect(trigger).toBeFocused();
  await expect(page.getByRole('region', { name: 'Your account' })).toHaveCount(0);
});

test('reduced motion disables screen, drawer, menu and link motion without blocking navigation', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await mockChat(page);
  await page.goto('/');
  expect(await page.locator('main').evaluate((element) => element.getAnimations().length)).toBe(0);
  await page.getByRole('textbox').fill('Tyres?');
  await page.getByRole('button', { name: 'Send question' }).click();
  await page.locator('.answer-content').getByRole('button', { name: /View source S1/ }).click();
  const drawer = page.getByRole('dialog');
  expect(await drawer.evaluate((element) => element.getAnimations().length)).toBe(0);
  const link = drawer.getByRole('link', { name: /Full regulations/ });
  expect(await link.evaluate((element) => getComputedStyle(element).transitionDuration)).toBe('0s');
  await page.keyboard.press('Escape');
  await expect(drawer).toHaveCount(0);
  await page.getByRole('button', { name: 'Go to welcome screen' }).click();
  await expect(page.getByRole('heading', { name: 'Know the rules.' })).toBeVisible();
});
