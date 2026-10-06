import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import { citation } from '../../src/test/citations';
import { conversationDetail } from '../../src/test/conversations';

const answer = 'Use **two different dry-weather tyre specifications** during the race. [S1]\n\n' +
  'The requirement applies unless intermediate or wet-weather tyres have been used. '.repeat(12) +
  '\n\n- Consult the regulations.\n- Keep the original evidence.\n\nFinal sentence. [S1]';

async function mockChat(page: Page) {
  const requests: Record<string, unknown>[] = [];
  await page.route('**/api/chat', async (route) => {
    requests.push(route.request().postDataJSON());
    await route.fulfill({ json: { answer, citations: [citation()], conversation_id: null } });
  });
  return requests;
}
async function ask(page: Page, message = 'Tyre requirements?') {
  await page.getByRole('textbox', { name: 'Your question' }).fill(message);
  await page.getByRole('button', { name: 'Send question' }).click();
}

test('new answers grow progressively with stable formatting and exact final citations', async ({ page }, info) => {
  await mockChat(page);
  await page.goto('/');
  await ask(page);
  const response = page.locator('.answer-response');
  await expect(response).toHaveAttribute('data-revealing', 'true');
  const initial = await response.locator('.answer-content').innerText();
  expect(initial).not.toContain('Final sentence');
  await expect(response.locator('.answer-content')).toContainText('two different');
  await expect(response.locator('strong')).toBeVisible();
  await expect(response.getByRole('group', { name: 'Sources' })).toHaveCount(0);
  const openingLength = (await response.locator('.answer-content').innerText()).length;
  await expect.poll(async () => (await response.locator('.answer-content').innerText()).length).toBeGreaterThan(openingLength);
  await page.screenshot({ path: info.outputPath('answer-progress.png') });
  await expect(response).not.toHaveAttribute('data-revealing', 'true');
  await expect(response).toContainText('Final sentence.');
  await expect(response.getByRole('listitem')).toHaveCount(2);
  const source = response.getByRole('group', { name: 'Sources' }).getByRole('button');
  await source.click();
  await expect(page.getByRole('dialog')).toContainText('PDF page 58');
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(source).toBeFocused();
  await page.screenshot({ path: info.outputPath('answer-complete.png') });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('show full answer completes instantly and follow-up history contains the full answer', async ({ page }) => {
  const requests = await mockChat(page);
  await page.goto('/');
  await ask(page);
  const skip = page.getByRole('button', { name: 'Show full answer' });
  await skip.focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('.answer-content')).toBeFocused();
  await expect(page.locator('.answer-content')).toContainText('Final sentence');
  await expect(skip).toHaveCount(0);
  const accessibility = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze();
  expect(accessibility.violations).toEqual([]);
  await ask(page, 'What happens if they fail?');
  expect(requests[1].history).toEqual([
    { role: 'user', content: 'Tyre requirements?' }, { role: 'assistant', content: answer },
  ]);
});

test('new chat removes an in-progress reveal and no old text can reappear', async ({ page }) => {
  await mockChat(page);
  await page.goto('/');
  await ask(page);
  await expect(page.getByRole('button', { name: 'Show full answer' })).toBeVisible();
  await page.getByRole('button', { name: 'Go to welcome screen' }).click();
  await expect(page.getByRole('log')).toHaveCount(0);
  await page.waitForTimeout(3200); // Past the maximum reveal duration, exercising cleanup.
  await expect(page.getByRole('heading', { name: 'Know the rules.' })).toBeVisible();
  await expect(page.locator('.answer-response')).toHaveCount(0);
});

test('reduced motion shows the complete answer immediately', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await mockChat(page);
  await page.goto('/');
  await ask(page);
  await expect(page.locator('.answer-content')).toContainText('Final sentence');
  await expect(page.getByRole('button', { name: 'Show full answer' })).toHaveCount(0);
  await expect(page.getByRole('group', { name: 'Sources' })).toBeVisible();
});

test('saved conversations reopen instantly without replaying old answers', async ({ page }) => {
  const detail = conversationDetail(1, 'Tyre rules');
  detail.messages[1].content = answer;
  await page.addInitScript(() => sessionStorage.setItem('pole-position:access-token', 'test-token'));
  await page.route('**/api/auth/me', (route) => route.fulfill({ json: { id: 1, username: 'assetk', created_at: '2026-10-05T12:00:00Z' } }));
  await page.route('**/api/conversations', (route) => route.fulfill({ json: [{ id: 1, title: detail.title, created_at: detail.created_at, updated_at: detail.updated_at }] }));
  await page.route('**/api/conversations/1', (route) => route.fulfill({ json: detail }));
  await page.goto('/');
  await expect(page.getByRole('button', { name: 'Account: assetk' })).toBeVisible();
  if (page.viewportSize()!.width <= 720) {
    await page.getByRole('button', { name: 'Navigation menu' }).click();
    await page.getByRole('button', { name: 'Saved chats', exact: true }).click();
  }
  await page.getByRole('button', { name: 'Open conversation: Tyre rules' }).click();
  await expect(page.locator('.answer-content')).toContainText('Final sentence');
  await expect(page.getByRole('button', { name: 'Show full answer' })).toHaveCount(0);
  await expect(page.getByRole('group', { name: 'Sources' })).toBeVisible();
});
