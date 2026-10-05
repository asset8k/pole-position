import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import { citation } from '../../src/test/citations';

const key = 'pole-position:access-token';
const identity = { id: 1, username: 'assetk', created_at: '2026-10-05T12:00:00Z' };
type Scenario = { loginStatus?: number; registerStatus?: number; meStatus?: number; chatStatus?: number };
async function mockApi(page: Page, scenario: Scenario = {}) {
  const requests: { path: string; auth?: string; body: unknown }[] = [];
  await page.route((url) => url.pathname.startsWith('/api/'), async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    requests.push({ path, auth: request.headers().authorization, body: request.postData() ? request.postDataJSON() : null });
    if (path === '/api/auth/login') {
      await route.fulfill(scenario.loginStatus
        ? { status: scenario.loginStatus, json: { detail: 'Incorrect username or password' } }
        : { json: { access_token: 'verified-token', token_type: 'bearer' } });
    } else if (path === '/api/auth/register') {
      await route.fulfill(scenario.registerStatus
        ? { status: scenario.registerStatus, json: { detail: 'Username already exists' } }
        : { status: 201, json: identity });
    } else if (path === '/api/auth/me') {
      await route.fulfill(scenario.meStatus
        ? { status: scenario.meStatus, json: { detail: 'Invalid token' } } : { json: identity });
    } else if (path === '/api/conversations') {
      await route.fulfill({ json: [] });
    } else if (path === '/api/chat') {
      await route.fulfill(scenario.chatStatus
        ? { status: scenario.chatStatus, json: { detail: 'Invalid token' } }
        : { json: { answer: 'A private answer. [S1]', citations: [citation()], conversation_id: 2 } });
    } else { await route.fulfill({ status: 404, json: { detail: 'Unexpected test request' } }); }
  });
  return requests;
}
async function open(page: Page) {
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  return page.getByRole('dialog');
}
async function fill(page: Page) {
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Username', { exact: true }).fill('assetk');
  await dialog.getByLabel('Password', { exact: true }).fill('securepassword123');
}
async function login(page: Page) {
  const dialog = await open(page);
  await fill(page);
  await dialog.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Account: assetk' })).toBeVisible();
}

test('auth forms are compact, keyboard-accessible, responsive, and dismiss with focus return', async ({ page }, testInfo) => {
  const requests = await mockApi(page);
  await page.goto('/');
  const trigger = page.getByRole('button', { name: 'Sign in', exact: true });
  const dialog = await open(page);
  await expect(dialog.getByRole('button', { name: 'Close sign in' })).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(dialog.getByLabel('Username')).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await page.keyboard.press('Shift+Tab');
  await expect(dialog.getByRole('button', { name: 'Create an account' })).toBeFocused();
  await page.screenshot({ path: testInfo.outputPath('sign-in.png'), fullPage: true });
  await dialog.getByRole('button', { name: 'Create an account' }).click();
  await expect(dialog.getByLabel('Password')).toHaveAttribute('autocomplete', 'new-password');
  await page.screenshot({ path: testInfo.outputPath('register.png'), fullPage: true });
  await page.keyboard.press('Escape');
  await expect(dialog).not.toBeVisible();
  await expect(trigger).toBeFocused();
  for (const width of [320, 390, 768, 1440]) {
    await page.setViewportSize({ width, height: 700 });
    const modal = await open(page);
    const box = await modal.boundingBox();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(width);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.keyboard.press('Escape');
    await expect(modal).not.toBeVisible();
  }
  expect(requests).toEqual([]);
});

test('invalid input, bad credentials, and duplicate usernames show errors without leaking secrets', async ({ page }) => {
  const scenario: Scenario = { loginStatus: 401, registerStatus: 409 };
  const requests = await mockApi(page, scenario);
  await page.goto('/');
  const dialog = await open(page);
  await dialog.getByLabel('Username').fill('AssetK');
  await dialog.getByLabel('Password').fill('short');
  await dialog.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(dialog.getByLabel('Username')).toHaveAttribute('aria-invalid', 'true');
  expect(requests).toEqual([]);
  await fill(page);
  await dialog.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(dialog.getByRole('alert')).toHaveText('Incorrect username or password.');
  await dialog.getByRole('button', { name: 'Create an account' }).click();
  await expect(dialog.getByLabel('Password')).toHaveValue('');
  await fill(page);
  await dialog.getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(dialog.getByRole('alert')).toContainText('already taken');
  expect(await page.evaluate((name) => sessionStorage.getItem(name), key)).toBeNull();
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain('securepassword123');
});

test('registration signs in, refresh restores via /me, and logout removes only its own token', async ({ page }) => {
  const requests = await mockApi(page);
  await page.goto('/');
  await page.evaluate(() => sessionStorage.setItem('unrelated', 'keep'));
  const dialog = await open(page);
  await dialog.getByRole('button', { name: 'Create an account' }).click();
  await fill(page);
  await dialog.getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Account: assetk' })).toBeVisible();
  expect(requests.filter((request) => request.path.startsWith('/api/auth/')).map((request) => request.path))
    .toEqual(['/api/auth/register', '/api/auth/login', '/api/auth/me']);
  expect(requests.find((request) => request.path === '/api/auth/me')?.auth).toBe('Bearer verified-token');
  await page.reload();
  await expect(page.getByRole('button', { name: 'Account: assetk' })).toBeVisible();
  expect(requests.filter((request) => request.path === '/api/auth/me').length).toBeGreaterThanOrEqual(2);
  await page.getByRole('button', { name: 'Account: assetk' }).click();
  await expect(page.getByRole('button', { name: 'Sign out' })).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('button', { name: 'Account: assetk' })).toBeFocused();
  await page.getByRole('button', { name: 'Account: assetk' }).click();
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible();
  expect(await page.evaluate((name) => sessionStorage.getItem(name), key)).toBeNull();
  expect(await page.evaluate(() => sessionStorage.getItem('unrelated'))).toBe('keep');
});

test('signed-in chat sends only token and conversation ID; logout clears private UI', async ({ page }) => {
  const requests = await mockApi(page);
  await page.goto('/');
  await login(page);
  await page.getByRole('textbox', { name: 'Your question' }).fill('Private question');
  await page.getByRole('button', { name: 'Send question' }).click();
  await expect(page.getByRole('group', { name: 'Sources' })).toBeVisible();
  await page.getByRole('textbox', { name: 'Your question' }).fill('Follow-up');
  await page.getByRole('button', { name: 'Send question' }).click();
  await expect(page.getByRole('log')).toContainText('Follow-up');
  await expect(page.getByRole('button', { name: 'Send question' })).toBeDisabled();
  await expect(page.locator('.chat-loading')).toHaveCount(0);
  const chat = requests.filter((request) => request.path === '/api/chat');
  expect(chat.map((request) => request.body)).toEqual([{ message: 'Private question' }, { message: 'Follow-up', conversation_id: 2 }]);
  expect(chat.every((request) => request.auth === 'Bearer verified-token')).toBe(true);
  await page.getByRole('textbox', { name: 'Your question' }).fill('Private draft');
  await page.getByRole('button', { name: 'Account: assetk' }).click();
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByRole('log')).toHaveCount(0);
  await expect(page.getByRole('textbox', { name: 'Your question' })).toHaveValue('');
  expect(await page.evaluate(() => JSON.stringify(sessionStorage))).not.toContain('Private');
});

test('expired restore and protected 401 responses clear the session instead of retrying as guest', async ({ page }) => {
  const scenario: Scenario = { meStatus: 401 };
  const requests = await mockApi(page, scenario);
  await page.addInitScript((name) => sessionStorage.setItem(name, 'expired-token'), key);
  await page.goto('/');
  await expect(page.getByRole('alert')).toContainText('expired');
  await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible();
  expect(await page.evaluate((name) => sessionStorage.getItem(name), key)).toBeNull();
  scenario.meStatus = undefined;
  await login(page);
  scenario.chatStatus = 401;
  await page.getByRole('textbox', { name: 'Your question' }).fill('Private question');
  await page.getByRole('button', { name: 'Send question' }).click();
  await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible();
  await expect(page.getByRole('log')).toHaveCount(0);
  expect(requests.filter((request) => request.path === '/api/chat')).toHaveLength(1);
});

test('verification failure blocks accidental guest sending and offers retry or guest mode', async ({ page }) => {
  const scenario: Scenario = { meStatus: 503 };
  await mockApi(page, scenario);
  await page.addInitScript((name) => sessionStorage.setItem(name, 'stored-token'), key);
  await page.goto('/');
  await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible();
  await expect(page.getByRole('textbox', { name: 'Your question' })).toHaveCount(0);
  expect(await page.evaluate((name) => sessionStorage.getItem(name), key)).toBe('stored-token');
  scenario.meStatus = undefined;
  await page.getByRole('button', { name: 'Retry' }).click();
  await expect(page.getByRole('button', { name: 'Account: assetk' })).toBeVisible();
  scenario.meStatus = 503;
  await page.reload();
  await page.getByRole('button', { name: 'Continue as guest' }).click();
  await expect(page.getByRole('textbox', { name: 'Your question' })).toBeVisible();
  expect(await page.evaluate((name) => sessionStorage.getItem(name), key)).toBeNull();
});
