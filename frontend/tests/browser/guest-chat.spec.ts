import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import type { ChatRequest } from '../../src/api/contracts';

const tyreAnswer = 'Unless intermediate or wet-weather tyres are used, each driver must use at least two different dry-tyre specifications during the race. [S1]';
const penaltyAnswer = 'Failure to comply results in disqualification. If the race is suspended and cannot restart, a 30-second penalty applies instead. [S1]';

function reply(answer = tyreAnswer) {
  return { answer, conversation_id: null, citations: [{
    source_id: 'S1', chunk_id: 'fia-f1-2026-section-b-issue-08:B6.3.6:0',
    document_id: 'fia-f1-2026-section-b-issue-08', document_title: 'Sporting Regulations',
    section: 'B', source_kind: 'clause', article_identifier: 'B6', clause_identifier: 'B6.3.6',
    appendix_identifier: null, start_pdf_page: 58, end_pdf_page: 58, snippet: 'Original regulation excerpt.',
  }] };
}

async function ask(page: Page, question: string) {
  await page.getByRole('textbox', { name: 'Your question' }).fill(question);
  await page.getByRole('button', { name: 'Send question' }).click();
}

async function newChat(page: Page, mobile: boolean) {
  if (mobile) await page.getByRole('button', { name: 'Navigation menu' }).click();
  await page.getByRole('button', { name: 'New chat', exact: true }).click();
}

test('guest sends, sees loading, and follows up with prior history only', async ({ page }, testInfo) => {
  const bodies: ChatRequest[] = [];
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  await page.route((url) => url.pathname.startsWith('/api/'), async (route) => {
    expect(new URL(route.request().url()).pathname).toBe('/api/chat');
    expect(route.request().headers().authorization).toBeUndefined();
    bodies.push(route.request().postDataJSON());
    if (bodies.length === 2) await gate;
    await route.fulfill({ json: reply(bodies.length === 1 ? tyreAnswer : penaltyAnswer) });
  });
  await page.goto('/');
  await ask(page, 'How many tyre specifications are required?');
  await expect(page.locator('.answer-content').filter({ hasText: tyreAnswer.replace(' [S1]', '') })).toBeVisible();
  expect(bodies[0]).toEqual({ message: 'How many tyre specifications are required?', history: [] });
  await expect(page.getByRole('textbox')).toHaveValue('');
  await page.screenshot({ path: testInfo.outputPath('guest-chat.png'), fullPage: true, animations: 'disabled' });

  await ask(page, 'What if the driver does not comply?');
  await expect(page.getByRole('status')).toHaveText('Checking the regulations…');
  await expect(page.getByRole('button', { name: 'Send question' })).toBeDisabled();
  await expect(page.getByRole('textbox')).toHaveAttribute('readonly');
  await page.getByRole('textbox').press('Enter');
  expect(bodies).toHaveLength(2);
  expect(bodies[1]).toEqual({ message: 'What if the driver does not comply?', history: [
    { role: 'user', content: 'How many tyre specifications are required?' },
    { role: 'assistant', content: tyreAnswer },
  ] });
  await page.screenshot({ path: testInfo.outputPath('guest-loading.png'), fullPage: true, animations: 'disabled' });
  release();
  await expect(page.locator('.answer-content').filter({ hasText: penaltyAnswer.replace(' [S1]', '') })).toBeVisible();
  await expect(page.getByRole('textbox')).not.toHaveAttribute('readonly');
  await expect(page.getByRole('log').getByRole('listitem')).toHaveCount(4);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('last-ten history does not discard older messages from the visible chat', async ({ page }) => {
  const bodies: ChatRequest[] = [];
  await page.route((url) => url.pathname.startsWith('/api/'), async (route) => {
    bodies.push(route.request().postDataJSON());
    await route.fulfill({ json: reply(`Answer ${bodies.length}`) });
  });
  await page.goto('/');
  for (let index = 1; index <= 7; index++) {
    await ask(page, `Question ${index}`);
    await expect(page.getByText(`Answer ${index}`, { exact: true })).toBeVisible();
  }
  expect(bodies[6].history).toEqual(Array.from({ length: 5 }, (_, index) => [
    { role: 'user', content: `Question ${index + 2}` },
    { role: 'assistant', content: `Answer ${index + 2}` },
  ]).flat());
  expect(bodies[6].history).toHaveLength(10);
  await expect(page.getByRole('log').getByRole('listitem')).toHaveCount(14);
  await expect(page.getByRole('log')).toContainText('Question 1');
});

test('an error restores the draft and resend does not duplicate the failed turn', async ({ page }, testInfo) => {
  const bodies: ChatRequest[] = [];
  await page.route((url) => url.pathname.startsWith('/api/'), async (route) => {
    bodies.push(route.request().postDataJSON());
    if (bodies.length === 1) {
      await route.fulfill({ status: 503, json: { detail: 'Private diagnostic' } });
    } else await route.fulfill({ json: reply() });
  });
  await page.goto('/');
  await ask(page, 'A question to retry');
  await expect(page.getByRole('alert')).toContainText('The server is unavailable');
  await expect(page.getByRole('textbox')).toHaveValue('A question to retry');
  await expect(page.getByText('Private diagnostic')).toHaveCount(0);
  expect(bodies).toHaveLength(1);
  await page.screenshot({ path: testInfo.outputPath('guest-error.png'), fullPage: true, animations: 'disabled' });
  await page.getByRole('button', { name: 'Send question' }).click();
  await expect(page.locator('.answer-content').filter({ hasText: tyreAnswer.replace(' [S1]', '') })).toBeVisible();
  expect(bodies[1]).toEqual(bodies[0]);
  await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(page.getByRole('log').getByText('A question to retry', { exact: true })).toHaveCount(1);
});

test('New chat ignores a late response and starts with empty history', async ({ page }, testInfo) => {
  const bodies: ChatRequest[] = [];
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  await page.route((url) => url.pathname.startsWith('/api/'), async (route) => {
    bodies.push(route.request().postDataJSON());
    if (bodies.length === 1) {
      await gate;
      // Fetch has been aborted; Playwright may already have disposed this route.
      await route.fulfill({ json: reply('Stale answer') }).catch(() => {});
    } else await route.fulfill({ json: reply('Fresh answer') });
  });
  await page.goto('/');
  await ask(page, 'Old question');
  await expect(page.getByRole('status')).toContainText('Checking');
  await newChat(page, testInfo.project.name === 'mobile');
  await expect(page.getByRole('heading', { name: 'Know the rules.' })).toBeVisible();
  await expect(page.getByRole('textbox')).toBeFocused();
  release();
  await ask(page, 'Fresh question');
  await expect(page.getByText('Fresh answer', { exact: true })).toBeVisible();
  await expect(page.getByText('Stale answer', { exact: true })).toHaveCount(0);
  expect(bodies[1]).toEqual({ message: 'Fresh question', history: [] });
  await newChat(page, testInfo.project.name === 'mobile');
  await expect(page.getByRole('log')).toHaveCount(0);
});

test('refresh clears guest messages and draft without using or clearing unrelated storage', async ({ page }) => {
  let requests = 0;
  await page.route((url) => url.pathname.startsWith('/api/'), async (route) => {
    requests++;
    await route.fulfill({ json: reply() });
  });
  await page.goto('/');
  await page.evaluate(() => {
    localStorage.setItem('unrelated', 'keep-local');
    sessionStorage.setItem('unrelated', 'keep-session');
  });
  await ask(page, 'Temporary question');
  await expect(page.locator('.answer-content').filter({ hasText: tyreAnswer.replace(' [S1]', '') })).toBeVisible();
  await page.getByRole('textbox').fill('Unsent draft');
  const storage = () => page.evaluate(() => ({
    local: { ...localStorage }, session: { ...sessionStorage },
    search: location.search, hash: location.hash,
  }));
  expect(await storage()).toEqual({ local: { unrelated: 'keep-local' }, session: { unrelated: 'keep-session' }, search: '', hash: '' });
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Know the rules.' })).toBeVisible();
  await expect(page.getByRole('textbox')).toHaveValue('');
  await expect(page.getByRole('log')).toHaveCount(0);
  expect(requests).toBe(1);
  expect(await storage()).toEqual({ local: { unrelated: 'keep-local' }, session: { unrelated: 'keep-session' }, search: '', hash: '' });
  expect(await page.context().cookies()).toEqual([]);
});

test('empty-citation answers render and raw HTML is not executed', async ({ page }) => {
  const answer = 'Not enough evidence. <img src="x" onerror="window.hacked=true">';
  await page.route((url) => url.pathname.startsWith('/api/'), (route) => route.fulfill({ json: { answer, citations: [], conversation_id: null } }));
  await page.goto('/');
  await ask(page, 'An unknown fact');
  await expect(page.getByText(answer, { exact: true })).toBeVisible();
  await expect(page.getByRole('log').locator('img')).toHaveCount(0);
  await expect(page.getByRole('alert')).toHaveCount(0);
});
