import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import type { ConversationDetailResponse } from '../../src/api/contracts';
import { citation } from '../../src/test/citations';
import { conversationDetail } from '../../src/test/conversations';

async function scan(page: Page) {
  const result = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze();
  expect(result.violations.map(({ id, nodes }) => ({ id, nodes: nodes.map(({ target, failureSummary }) => ({ target, failureSummary })) }))).toEqual([]);
}
async function ask(page: Page, question: string) {
  await page.getByRole('textbox', { name: 'Your question' }).fill(question);
  await page.getByRole('button', { name: 'Send question' }).click();
}
async function history(page: Page) {
  if (page.viewportSize()!.width > 720) return page.getByRole('complementary', { name: 'Your saved chats' });
  await page.getByRole('button', { name: 'Navigation menu' }).click();
  await page.getByRole('button', { name: 'Saved chats', exact: true }).click();
  return page.getByRole('dialog', { name: 'Saved chats' });
}

test('complete mocked guest/account journey and accessibility scans', async ({ page }, info) => {
  const records = new Map<number, ConversationDetailResponse>();
  const chats: { body: Record<string, unknown>; auth?: string }[] = [];
  const identity = { id: 1, username: 'assetk', created_at: '2026-10-05T12:00:00Z' };
  let failed = false;
  await page.route((url) => url.pathname.startsWith('/api/'), async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const body = request.postData() ? request.postDataJSON() as Record<string, unknown> : {};
    if (path === '/api/auth/login') return route.fulfill({ json: { access_token: 'journey-token', token_type: 'bearer' } });
    if (path === '/api/auth/me') return route.fulfill({ json: identity });
    if (path === '/api/conversations') return route.fulfill({ json: [...records.values()].map(({ messages: _messages, ...metadata }) => metadata) });
    if (path === '/api/chat') {
      const auth = request.headers().authorization;
      chats.push({ body, auth });
      if (body.message === 'Unavailable' && !failed) { failed = true; return route.fulfill({ status: 503 }); }
      const id = auth ? 1 : null;
      const answer = '## Tyre rules\n\nUse **two specifications**. [S1]\n\n```text\nB6.3.6\n```';
      if (id) {
        const item = records.get(id) ?? { ...conversationDetail(id, String(body.message)), messages: [] };
        const start = item.messages.length;
        item.messages.push(
          { id: start + 1, conversation_id: id, role: 'user', content: String(body.message), citations: [], created_at: identity.created_at },
          { id: start + 2, conversation_id: id, role: 'assistant', content: answer, citations: [citation()], created_at: identity.created_at },
        );
        records.set(id, item);
      }
      return route.fulfill({ json: { answer, citations: [citation()], conversation_id: id } });
    }
    if (path === '/api/conversations/1') {
      const item = records.get(1);
      if (!item) return route.fulfill({ status: 404 });
      if (request.method() === 'DELETE') { records.delete(1); return route.fulfill({ status: 204 }); }
      if (request.method() === 'PATCH') item.title = String(body.title);
      return route.fulfill({ json: item });
    }
    return route.fulfill({ status: 404 });
  });
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/');
  await scan(page);
  await ask(page, 'Guest tyres');
  await expect(page.getByRole('group', { name: 'Sources' })).toBeVisible();
  await scan(page);
  await page.getByRole('group', { name: 'Sources' }).getByRole('button').click();
  await expect(page.getByRole('dialog', { name: 'Source S1' })).toBeVisible();
  await scan(page);
  await page.screenshot({ path: info.outputPath('source-final.png'), animations: 'disabled' });
  await page.keyboard.press('Escape');
  await ask(page, 'And the penalty?');
  await expect(page.getByRole('group', { name: 'Sources' })).toHaveCount(2);
  expect(chats[1].body.history).toHaveLength(2);
  await ask(page, 'Unavailable');
  await expect(page.getByRole('alert')).toBeVisible();
  await scan(page);

  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  const auth = page.getByRole('dialog');
  await scan(page);
  await auth.getByRole('button', { name: 'Create an account' }).click();
  await auth.getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(auth.getByLabel('Username')).toHaveAttribute('aria-invalid', 'true');
  await scan(page);
  await auth.getByRole('button', { name: 'Sign in instead' }).click();
  await auth.getByLabel('Username').fill('assetk');
  await auth.getByLabel('Password').fill('securepassword123');
  await auth.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Account: assetk' })).toBeVisible();
  await expect(page.getByRole('log')).toHaveCount(0);
  await ask(page, 'Saved tyres');
  await expect(page.getByRole('group', { name: 'Sources' })).toBeVisible();
  expect(chats.at(-1)).toEqual({ body: { message: 'Saved tyres' }, auth: 'Bearer journey-token' });
  await scan(page);
  const panel = await history(page);
  await expect(panel.getByRole('button', { name: 'Open conversation: Saved tyres' })).toBeVisible();
  await scan(page);
  await panel.getByRole('button', { name: 'Rename conversation: Saved tyres' }).click();
  const rename = page.getByRole('dialog', { name: 'Rename conversation' });
  await scan(page);
  await rename.getByLabel('Conversation title').fill('Race tyres');
  await rename.getByRole('button', { name: 'Save title' }).click();
  await expect(rename).not.toBeVisible();
  await page.reload();
  await expect(page.getByRole('button', { name: 'Account: assetk' })).toBeVisible();
  await (await history(page)).getByRole('button', { name: 'Open conversation: Race tyres' }).click();
  await expect(page.getByRole('log')).toContainText('Saved tyres');
  await ask(page, 'What if they fail?');
  await expect(page.getByRole('group', { name: 'Sources' })).toHaveCount(2);
  expect(chats.at(-1)).toEqual({ body: { message: 'What if they fail?', conversation_id: 1 }, auth: 'Bearer journey-token' });
  await page.screenshot({ path: info.outputPath('chat-final.png'), fullPage: true, animations: 'disabled' });
  await (await history(page)).getByRole('button', { name: 'Delete conversation: Race tyres' }).click();
  const deletion = page.getByRole('dialog', { name: 'Delete conversation?' });
  await scan(page);
  await deletion.getByRole('button', { name: 'Cancel' }).click();
  expect(records.size).toBe(1);
  const restored = page.viewportSize()!.width <= 720 ? page.getByRole('dialog', { name: 'Saved chats' }) : await history(page);
  await restored.getByRole('button', { name: 'Delete conversation: Race tyres' }).click();
  await deletion.getByRole('button', { name: 'Delete conversation', exact: true }).click();
  await expect(deletion).not.toBeVisible();
  expect(records.size).toBe(0);
  if (page.viewportSize()!.width <= 720) await page.keyboard.press('Escape');
  await expect(page.getByRole('log')).toHaveCount(0);
  await page.getByRole('button', { name: 'Account: assetk' }).click();
  await scan(page);
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});

test('late replies preserve older reading position and expose an explicit jump', async ({ page }) => {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  let calls = 0;
  const long = Array.from({ length: 30 }, (_, index) => `Paragraph ${index}: ${'A regulation passage. '.repeat(12)}`).join('\n\n');
  await page.route((url) => url.pathname.startsWith('/api/'), async (route) => {
    calls++;
    if (calls === 2) await gate;
    await route.fulfill({ json: { answer: calls === 1 ? long : 'New reply at the bottom.', citations: [], conversation_id: null } });
  });
  await page.goto('/');
  await ask(page, 'Long answer');
  await expect(page.getByText(/Paragraph 29:/)).toBeVisible();
  await ask(page, 'Follow up');
  await expect(page.getByRole('status')).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 250));
  await expect.poll(() => page.evaluate(() => scrollY)).toBe(250);
  // Allow the real scroll listener to record intent before resolving the request.
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  release();
  await expect(page.getByRole('button', { name: 'Jump to latest' })).toBeInViewport();
  expect(await page.evaluate(() => scrollY)).toBe(250);
  await page.getByRole('button', { name: 'Jump to latest' }).click();
  await expect(page.getByText('New reply at the bottom.', { exact: true })).toBeVisible();
  await expect(page.getByRole('textbox', { name: 'Your question' })).toBeFocused();
});

test('short screens, zoom-equivalent reflow and high-contrast/reduced-glass preferences', async ({ page }, info) => {
  await page.route((url) => url.pathname.startsWith('/api/'), (route) => route.fulfill({ json: { answer: 'A concise answer. [S1]', citations: [citation()], conversation_id: null } }));
  await page.goto('/');
  // Half a 1280px desktop layout viewport is the CSS reflow equivalent of 200% zoom.
  for (const size of [{ width: 640, height: 400 }, { width: 320, height: 568 }, { width: 844, height: 390 }]) {
    await page.setViewportSize(size);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await dialog.getByLabel('Password').fill('password123');
    await expect(dialog.getByRole('button', { name: 'Sign in', exact: true })).toBeInViewport();
    await page.keyboard.press('Escape');
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await ask(page, 'Tyres');
  await expect(page.getByRole('group', { name: 'Sources' })).toBeVisible();
  await page.emulateMedia({ reducedMotion: 'reduce', forcedColors: 'active' });
  await scan(page);
  await page.screenshot({ path: info.outputPath('high-contrast.png'), fullPage: true });
  await page.emulateMedia({ forcedColors: 'none' });
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-transparency', value: 'reduce' }, { name: 'prefers-reduced-motion', value: 'reduce' }] });
  expect(await page.locator('.composer').evaluate((element) => getComputedStyle(element).backgroundColor)).toBe('rgb(41, 39, 45)');
  await page.getByRole('group', { name: 'Sources' }).getByRole('button').click();
  expect(await page.getByRole('dialog').evaluate((element) => getComputedStyle(element).backdropFilter)).toBe('none');
  await scan(page);
  await page.screenshot({ path: info.outputPath('solid-source.png'), animations: 'disabled' });
});

test('simulated visual-only keyboard resize keeps the composer and dialogs reachable', async ({ page }) => {
  // Deterministic API simulation, not a claim of real iOS/Android keyboard testing.
  await page.addInitScript(() => {
    const viewport = Object.assign(new EventTarget(), { height: innerHeight, offsetTop: 0, scale: 1 });
    Object.defineProperty(window, 'visualViewport', { configurable: true, value: viewport });
    Object.assign(window, { resizeVisible: (height: number, scale = 1) => { viewport.height = height; viewport.scale = scale; viewport.dispatchEvent(new Event('resize')); } });
  });
  await page.route((url) => url.pathname.startsWith('/api/'), (route) => route.fulfill({ json: { answer: 'Tyre answer.', citations: [], conversation_id: null } }));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await ask(page, 'Tyres');
  await expect(page.getByText('Tyre answer.', { exact: true })).toBeVisible();
  await page.getByRole('textbox').focus();
  await page.evaluate(() => (window as unknown as { resizeVisible: (height: number) => void }).resizeVisible(420));
  await expect.poll(() => page.locator('html').evaluate((element) => element.style.getPropertyValue('--visual-bottom'))).toBe('424px');
  const box = await page.locator('.composer').boundingBox();
  expect(box!.y + box!.height).toBeLessThanOrEqual(421);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  const auth = page.getByRole('dialog');
  await auth.getByLabel('Password').focus();
  const bounds = await auth.boundingBox();
  expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(420);
  await page.keyboard.press('Escape');
  await page.evaluate(() => (window as unknown as { resizeVisible: (height: number, scale: number) => void }).resizeVisible(420, 2));
  await expect.poll(() => page.locator('html').evaluate((element) => element.style.getPropertyValue('--visual-bottom'))).toBe('0px');
});
