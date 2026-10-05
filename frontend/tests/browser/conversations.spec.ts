import { expect, test } from '@playwright/test';
import type { Locator, Page } from '@playwright/test';
import type { ConversationDetailResponse } from '../../src/api/contracts';
import { conversationDetail } from '../../src/test/conversations';
import { citation } from '../../src/test/citations';

interface Scenario {
  listStatus?: number; getStatus?: number; deleteStatus?: number; renameStatus?: number;
  slowGet?: number; wait?: Promise<void>;
}
async function server(page: Page, scenario: Scenario = {}) {
  const records = new Map<number, ConversationDetailResponse>([
    [1, conversationDetail(1, 'Tyre rules')], [2, conversationDetail(2, 'Cost cap')],
  ]);
  const requests: { path: string; method: string; body: Record<string, unknown> | null; auth?: string }[] = [];
  let next = 3;
  await page.route((url) => url.pathname.startsWith('/api/'), async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();
    const body = request.postData() ? request.postDataJSON() as Record<string, unknown> : null;
    requests.push({ path, method, body, auth: request.headers().authorization });
    if (path === '/api/auth/me') {
      await route.fulfill({ json: { id: 1, username: 'assetk', created_at: '2026-10-05T12:00:00Z' } }); return;
    }
    if (path === '/api/conversations') {
      await route.fulfill(scenario.listStatus ? { status: scenario.listStatus, json: { detail: 'Unavailable' } }
        : { json: [...records.values()].map(({ messages: _messages, ...item }) => item) }); return;
    }
    const match = /^\/api\/conversations\/(\d+)$/.exec(path);
    if (match) {
      const id = Number(match[1]);
      const item = records.get(id);
      const status = method === 'GET' ? scenario.getStatus : method === 'DELETE' ? scenario.deleteStatus : scenario.renameStatus;
      if (status || !item) { await route.fulfill({ status: status ?? 404, json: { detail: 'Conversation not found' } }); return; }
      if (method === 'GET') {
        const snapshot = JSON.parse(JSON.stringify(item)) as ConversationDetailResponse;
        if (scenario.slowGet === id) {
          await scenario.wait;
          // The UI intentionally cancels a superseded detail request.
          try { await route.fulfill({ json: snapshot }); } catch { /* Request already aborted. */ }
        } else await route.fulfill({ json: snapshot });
      } else if (method === 'PATCH') {
        item.title = String(body?.title); item.updated_at = '2026-10-06T12:00:00Z';
        const { messages: _messages, ...metadata } = item;
        await route.fulfill({ json: metadata });
      } else if (method === 'DELETE') { records.delete(id); await route.fulfill({ status: 204 }); }
      return;
    }
    if (path === '/api/chat') {
      const id = typeof body?.conversation_id === 'number' ? body.conversation_id : next++;
      let item = records.get(id);
      if (!item) { item = { ...conversationDetail(id, String(body?.message).slice(0, 160)), messages: [] }; records.set(id, item); }
      const answer = `Latest answer for ${item.title}. [S1]`;
      item.messages.push(
        { id: id * 100 + item.messages.length + 1, conversation_id: id, role: 'user', content: String(body?.message), citations: [], created_at: '2026-10-06T12:00:00Z' },
        { id: id * 100 + item.messages.length + 2, conversation_id: id, role: 'assistant', content: answer, citations: [citation()], created_at: '2026-10-06T12:00:00Z' },
      );
      item.updated_at = '2026-10-06T12:00:00Z';
      await route.fulfill({ json: { answer, citations: [citation()], conversation_id: id } }); return;
    }
    await route.fulfill({ status: 404, json: { detail: 'Unexpected request' } });
  });
  await page.addInitScript(() => sessionStorage.setItem('pole-position:access-token', 'account-token'));
  await page.goto('/');
  await expect(page.getByRole('button', { name: 'Account: assetk' })).toBeVisible();
  return { records, requests };
}

async function list(page: Page): Promise<Locator> {
  if (page.viewportSize()!.width <= 720) {
    const visible = page.getByRole('dialog', { name: 'Saved chats' });
    if (!await visible.isVisible()) {
      await page.getByRole('button', { name: 'Navigation menu' }).click();
      await page.getByRole('button', { name: 'Saved chats', exact: true }).click();
    }
    return visible;
  }
  return page.getByRole('complementary', { name: 'Your saved chats' });
}
async function open(page: Page, title: string) {
  const panel = await list(page);
  await panel.getByRole('button', { name: `Open conversation: ${title}`, exact: true }).click();
  await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible();
}
async function ask(page: Page, question: string) {
  await page.getByRole('textbox', { name: 'Your question' }).fill(question);
  await page.getByRole('button', { name: 'Send question' }).click();
  await expect(page.locator('.chat-loading')).toHaveCount(0);
}

test('reopening restores messages/citations; authenticated follow-ups persist across refresh', async ({ page }, testInfo) => {
  const api = await server(page);
  await open(page, 'Tyre rules');
  await expect(page.getByRole('log')).toContainText('Saved answer for Tyre rules.');
  await page.getByRole('group', { name: 'Sources' }).getByRole('button').click();
  await expect(page.getByRole('dialog', { name: 'Source S1' })).toContainText('PDF page 58');
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog', { name: 'Source S1' })).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath('saved-conversation.png'), fullPage: true });
  await ask(page, 'What happens if they fail?');
  await expect(page.getByRole('log')).toContainText('Latest answer for Tyre rules.');
  expect(api.requests.find((request) => request.path === '/api/chat')).toMatchObject({
    auth: 'Bearer account-token', body: { message: 'What happens if they fail?', conversation_id: 1 },
  });
  expect(api.requests.find((request) => request.path === '/api/chat')?.body).not.toHaveProperty('history');
  await page.reload();
  await open(page, 'Tyre rules');
  await expect(page.getByRole('log')).toContainText('What happens if they fail?');
  await expect(page.getByRole('log')).toContainText('Saved answer for Tyre rules.');
  await expect(page.getByRole('group', { name: 'Sources' })).toHaveCount(2);
  expect(api.requests.every((request) => request.auth === 'Bearer account-token')).toBe(true);
});

test('new chat automatically saves and appears in navigation, with no prior conversation ID', async ({ page }) => {
  const api = await server(page);
  await open(page, 'Tyre rules');
  const panel = await list(page);
  await panel.getByRole('button', { name: 'New conversation' }).click();
  await expect(page.getByRole('heading', { name: 'Know the rules.' })).toBeVisible();
  await ask(page, 'Power unit limits');
  await expect(page.getByRole('log')).toContainText('Latest answer for Power unit limits.');
  const updated = await list(page);
  await expect(updated.getByRole('button', { name: 'Open conversation: Power unit limits' })).toHaveAttribute('aria-current', 'page');
  expect(api.requests.find((request) => request.path === '/api/chat')?.body).toEqual({ message: 'Power unit limits' });
  await updated.getByRole('button', { name: 'Open conversation: Tyre rules' }).click();
  await expect(page.getByRole('heading', { name: 'Tyre rules' })).toBeVisible();
});

test('rename validates locally, cancellation is harmless, and the new title survives reopening', async ({ page }) => {
  const api = await server(page);
  await open(page, 'Tyre rules');
  await (await list(page)).getByRole('button', { name: 'Rename conversation: Tyre rules' }).click();
  const dialog = page.getByRole('dialog', { name: 'Rename conversation' });
  await dialog.getByLabel('Conversation title').fill(' ');
  await dialog.getByRole('button', { name: 'Save title' }).click();
  await expect(dialog.getByLabel('Conversation title')).toHaveAttribute('aria-invalid', 'true');
  expect(api.requests.filter((request) => request.method === 'PATCH')).toEqual([]);
  await dialog.getByRole('button', { name: 'Cancel' }).click();
  await (await list(page)).getByRole('button', { name: 'Rename conversation: Tyre rules' }).click();
  await dialog.getByLabel('Conversation title').fill('  Race tyres  ');
  await dialog.getByRole('button', { name: 'Save title' }).click();
  await expect(dialog).not.toBeVisible();
  const updated = await list(page);
  await expect(updated.getByRole('button', { name: 'Open conversation: Race tyres' })).toBeVisible();
  expect(api.requests.find((request) => request.method === 'PATCH')?.body).toEqual({ title: 'Race tyres' });
  if (page.viewportSize()!.width <= 720) await page.keyboard.press('Escape');
  await expect(page.getByRole('heading', { name: 'Race tyres', exact: true })).toBeVisible();
  await page.reload();
  await open(page, 'Race tyres');
});

test('delete requires confirmation, accepts 204, clears the selected chat, and stays deleted after refresh', async ({ page }) => {
  const api = await server(page);
  await open(page, 'Tyre rules');
  await (await list(page)).getByRole('button', { name: 'Delete conversation: Tyre rules' }).click();
  const dialog = page.getByRole('dialog', { name: 'Delete conversation?' });
  await dialog.getByRole('button', { name: 'Cancel' }).click();
  expect(api.requests.filter((request) => request.method === 'DELETE')).toEqual([]);
  await (await list(page)).getByRole('button', { name: 'Delete conversation: Tyre rules' }).click();
  await dialog.getByRole('button', { name: 'Delete conversation', exact: true }).click();
  await expect(dialog).not.toBeVisible();
  const updated = await list(page);
  await expect(updated.getByRole('button', { name: 'Open conversation: Tyre rules' })).toHaveCount(0);
  expect(api.requests.filter((request) => request.method === 'DELETE')).toHaveLength(1);
  if (page.viewportSize()!.width <= 720) await page.keyboard.press('Escape');
  await expect(page.getByRole('heading', { name: 'Know the rules.' })).toBeVisible();
  await expect(page.getByRole('log')).toHaveCount(0);
  await page.reload();
  await expect((await list(page)).getByRole('button', { name: 'Open conversation: Tyre rules' })).toHaveCount(0);
});

test('a late detail response cannot replace a more recently selected conversation', async ({ page }) => {
  let release!: () => void;
  const wait = new Promise<void>((resolve) => { release = resolve; });
  const api = await server(page, { slowGet: 1, wait });
  await (await list(page)).getByRole('button', { name: 'Open conversation: Tyre rules' }).click();
  await expect(page.getByText('Opening conversation…')).toBeVisible();
  await open(page, 'Cost cap');
  release();
  await expect(page.getByRole('heading', { name: 'Cost cap', exact: true })).toBeVisible();
  await expect(page.getByRole('log')).not.toContainText('Saved answer for Tyre rules.');
  await ask(page, 'What is included?');
  await expect(page.getByRole('log')).toContainText('Latest answer for Cost cap.');
  expect(api.requests.find((request) => request.path === '/api/chat')?.body?.conversation_id).toBe(2);
});

test('an inaccessible saved conversation never shows another transcript or allows a follow-up', async ({ page }) => {
  const scenario: Scenario = {};
  const api = await server(page, scenario);
  await open(page, 'Tyre rules');
  scenario.getStatus = 404;
  await (await list(page)).getByRole('button', { name: 'Open conversation: Cost cap' }).click();
  await expect(page.getByRole('alert')).toContainText('accessible');
  await expect(page.getByRole('log')).toHaveCount(0);
  await expect(page.getByRole('textbox', { name: 'Your question' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Start a new chat' }).click();
  await expect(page.getByRole('textbox', { name: 'Your question' })).toHaveValue('');
  expect(api.requests.filter((request) => request.path === '/api/chat')).toHaveLength(0);
});

test('list, detail, and mutation failures offer retry without losing or deleting saved data', async ({ page }) => {
  const scenario: Scenario = { listStatus: 503 };
  const api = await server(page, scenario);
  const panel = await list(page);
  await expect(panel.getByRole('alert')).toContainText('unavailable');
  scenario.listStatus = undefined;
  await panel.getByRole('button', { name: 'Retry list' }).click();
  await expect(panel.getByRole('button', { name: 'Open conversation: Tyre rules' })).toBeVisible();
  scenario.getStatus = 503;
  await panel.getByRole('button', { name: 'Open conversation: Tyre rules' }).click();
  await expect(page.getByRole('button', { name: 'Retry conversation' })).toBeVisible();
  scenario.getStatus = undefined;
  await page.getByRole('button', { name: 'Retry conversation' }).click();
  await expect(page.getByRole('heading', { name: 'Tyre rules', exact: true })).toBeVisible();
  scenario.deleteStatus = 503;
  await (await list(page)).getByRole('button', { name: 'Delete conversation: Tyre rules' }).click();
  const dialog = page.getByRole('dialog', { name: 'Delete conversation?' });
  await dialog.getByRole('button', { name: 'Delete conversation', exact: true }).click();
  await expect(dialog.getByRole('alert')).toContainText('unavailable');
  expect(api.records.has(1)).toBe(true);
  await dialog.getByRole('button', { name: 'Cancel' }).click();
  await expect((await list(page)).getByRole('button', { name: 'Open conversation: Tyre rules' })).toBeVisible();
});

test('saved navigation fits desktop/tablet/mobile; modal keyboard focus and Escape work', async ({ page }, testInfo) => {
  await server(page);
  for (const width of [320, 390, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    const panel = await list(page);
    await expect(panel.getByRole('button', { name: 'Open conversation: Tyre rules' })).toBeVisible();
    if (width <= 720) {
      await expect(panel.getByRole('button', { name: 'Close saved chats' })).toBeFocused();
      await page.keyboard.press('Shift+Tab');
      await expect(panel.getByRole('button', { name: 'Delete conversation: Tyre rules' })).toBeFocused();
      await page.screenshot({ path: testInfo.outputPath(`saved-navigation-${width}.png`), fullPage: true });
      await page.keyboard.press('Escape');
      await expect(page.getByRole('button', { name: 'Navigation menu' })).toBeFocused();
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
});
