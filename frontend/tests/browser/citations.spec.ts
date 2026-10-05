import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import { citation } from '../../src/test/citations';

async function ask(page: Page, question: string) {
  await page.getByRole('textbox').fill(question);
  await page.getByRole('button', { name: 'Send question' }).click();
}

test('formatted citations open their own excerpt with modal focus and Escape restoration', async ({ page }, testInfo) => {
  let requests = 0;
  await page.route((url) => url.pathname.startsWith('/api/'), (route) => {
    requests++;
    return route.fulfill({ json: { answer: '**Dry race tyre rule**\n\n- Use at least **two different specifications**.\n- At least one must be a mandatory race specification. [S1]', citations: [citation()], conversation_id: null } });
  });
  await page.goto('/');
  await ask(page, 'What is the dry race tyre rule?');
  const answer = page.locator('.answer-content');
  await expect(answer.locator('strong').first()).toHaveText('Dry race tyre rule');
  await expect(answer.getByRole('listitem')).toHaveCount(2);
  await page.screenshot({ path: testInfo.outputPath('formatted-answer.png'), fullPage: true, animations: 'disabled' });
  const trigger = answer.getByRole('button', { name: 'View source S1: B6.3.6' });
  await expect(trigger).toHaveAttribute('title', 'Sporting Regulations · PDF page 58');
  await trigger.focus();
  await page.keyboard.press('Enter');
  const drawer = page.getByRole('dialog', { name: 'Source S1' });
  const close = drawer.getByRole('button', { name: 'Close source' });
  const details = drawer.getByRole('region', { name: 'Source details' });
  const official = drawer.getByRole('link', { name: /Full regulations/ });
  await expect(drawer).toBeVisible();
  await expect(close).toBeFocused();
  await expect(drawer.getByText('Sporting Regulations', { exact: true })).toBeVisible();
  await expect(drawer.getByText('PDF page 58', { exact: true })).toBeVisible();
  expect(await drawer.locator('.source-excerpt p').textContent()).toBe(citation().snippet);
  await page.keyboard.press('Tab');
  await expect(details).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(official).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(close).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await expect(official).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await expect(details).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.style.overflow)).toBe('hidden');
  await drawer.evaluate((element) => Promise.all(element.getAnimations().map((motion) => motion.finished)));
  const bounds = (await drawer.boundingBox())!;
  const viewport = page.viewportSize()!;
  expect(bounds.x).toBeGreaterThanOrEqual(0);
  expect(bounds.x + bounds.width).toBeLessThanOrEqual(viewport.width);
  if (testInfo.project.name === 'mobile') expect(bounds.y).toBeGreaterThan(0);
  else expect(bounds.x).toBeGreaterThan(0);
  await page.screenshot({ path: testInfo.outputPath('source-drawer.png'), fullPage: true, animations: 'disabled' });
  await page.keyboard.press('Escape');
  await expect(drawer).toHaveCount(0);
  await expect(trigger).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.style.overflow)).toBe('');
  expect(requests).toBe(1); // Opening a citation makes no extra API/model calls.
});

test('S1 remains message-local across follow-ups and source chips work too', async ({ page }) => {
  let requests = 0;
  await page.route((url) => url.pathname.startsWith('/api/'), (route) => {
    requests++;
    const source = requests === 1 ? citation() : citation({ section: 'D', article_identifier: 'D1', clause_identifier: 'D1.2.1',
      document_title: 'Financial Regulations (F1 Teams)', start_pdf_page: 4, end_pdf_page: 5, snippet: 'Full cost cap excerpt, including its qualifications.' });
    return route.fulfill({ json: { answer: `${requests === 1 ? 'Tyre rule' : 'Cost cap rule'} [S1]`, citations: [source], conversation_id: null } });
  });
  await page.goto('/');
  await ask(page, 'Tyres?');
  await expect(page.locator('.chat-message--assistant')).toHaveCount(1);
  await ask(page, 'What about the cost cap?');
  const answers = page.locator('.chat-message--assistant');
  await expect(answers).toHaveCount(2);
  const oldTrigger = answers.nth(0).locator('.answer-content').getByRole('button', { name: /View source S1/ });
  await oldTrigger.click();
  await expect(page.getByRole('dialog').getByText('Sporting Regulations', { exact: true })).toBeVisible();
  await expect(page.getByRole('dialog').getByText('PDF page 58', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Close source' }).click();
  await expect(oldTrigger).toBeFocused();
  const newTrigger = answers.nth(1).getByRole('group', { name: 'Sources' }).getByRole('button', { name: /View source S1/ });
  await newTrigger.click();
  await expect(page.getByRole('dialog').getByText('Financial Regulations (F1 Teams)', { exact: true })).toBeVisible();
  await expect(page.getByRole('dialog').getByText('PDF pages 4–5', { exact: true })).toBeVisible();
  await page.mouse.click(8, 8); // Native backdrop outside both desktop and mobile drawers.
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(newTrigger).toBeFocused();
  expect(requests).toBe(2);
});

test('long appendix excerpts remain complete and keyboard-scrollable', async ({ page }) => {
  const snippet = Array.from({ length: 60 }, (_, index) => `Paragraph ${index + 1}: original appendix text and qualifications.`).join('\n\n');
  await page.route((url) => url.pathname.startsWith('/api/'), (route) => route.fulfill({ json: {
    answer: 'See the appendix. [S1]', conversation_id: null,
    citations: [citation({ source_kind: 'appendix', appendix_identifier: 'B2', article_identifier: null,
      clause_identifier: null, start_pdf_page: 86, end_pdf_page: 87, snippet })],
  } }));
  await page.goto('/');
  await ask(page, 'An appendix question');
  await page.locator('.answer-content').getByRole('button', { name: 'View source S1: Appendix B2' }).click();
  await expect(page.getByRole('dialog').getByText('PDF pages 86–87', { exact: true })).toBeVisible();
  expect(await page.locator('.source-excerpt p').textContent()).toBe(snippet);
  const details = page.getByRole('region', { name: 'Source details' });
  await expect(page.getByRole('link', { name: /Full regulations/ })).toBeInViewport();
  await details.focus();
  await page.keyboard.press('End');
  await expect.poll(() => details.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
  await expect(page.getByRole('link', { name: /Full regulations/ })).toBeInViewport();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
});

test('preamble and empty-citation answers do not invent clause metadata or sources', async ({ page }) => {
  let requests = 0;
  await page.route((url) => url.pathname.startsWith('/api/'), (route) => {
    requests++;
    return route.fulfill({ json: requests === 1 ? {
      answer: 'The preamble describes the objectives. [S1]', conversation_id: null,
      citations: [citation({ section: 'A', source_kind: 'preamble', article_identifier: null,
        clause_identifier: null, document_title: 'General Provisions', start_pdf_page: 4, end_pdf_page: 4 })],
    } : { answer: 'There is not enough evidence to answer. [S99]', citations: [], conversation_id: null } });
  });
  await page.goto('/');
  await ask(page, 'What objectives?');
  await page.locator('.answer-content').getByRole('button', { name: 'View source S1: Preamble' }).click();
  await expect(page.getByRole('dialog').getByText('Preamble', { exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await ask(page, 'An unknown fact?');
  const newest = page.locator('.chat-message--assistant').last();
  await expect(newest).toContainText('There is not enough evidence to answer. [S99]');
  await expect(newest.getByRole('button')).toHaveCount(0);
  await expect(newest.getByRole('group', { name: 'Sources' })).toHaveCount(0);
});

test('untrusted formatting neither executes HTML nor loads remote resources', async ({ page }) => {
  const remote: string[] = [];
  page.on('request', (request) => { if (new URL(request.url()).hostname !== '127.0.0.1') remote.push(request.url()); });
  await page.route((url) => url.pathname.startsWith('/api/'), (route) => route.fulfill({ json: {
    answer: '**Safe bold**\n\n<img src="https://evil.test/pixel" onerror="window.hacked=true">\n\n[Bad link](javascript:alert%281%29) ![Remote alt](https://evil.test/image)\n\n`[S1]`',
    citations: [], conversation_id: null,
  } }));
  await page.goto('/');
  await ask(page, 'Formatting test');
  const answer = page.locator('.answer-content');
  await expect(answer.locator('strong')).toHaveText('Safe bold');
  await expect(answer.locator('a, img, script, iframe, svg, button')).toHaveCount(0);
  await expect(answer).toContainText('Remote alt');
  expect(await page.evaluate(() => 'hacked' in window)).toBe(false);
  expect(remote).toEqual([]);
});

test('tables and source controls stay inside narrow viewports', async ({ page }) => {
  await page.route((url) => url.pathname.startsWith('/api/'), (route) => route.fulfill({ json: {
    answer: '| Axis | Direction | Additional detail |\n| --- | --- | --- |\n| X | Rearwards | Long coordinate description |\n\nSource [S1]',
    citations: [citation()], conversation_id: null,
  } }));
  for (const width of [320, 390, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/');
    await ask(page, 'Coordinate table');
    await expect(page.getByRole('table')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.locator('.answer-content').getByRole('button', { name: /View source S1/ }).click();
    const drawer = page.getByRole('dialog');
    await drawer.evaluate((element) => Promise.all(element.getAnimations().map((motion) => motion.finished)));
    const bounds = (await drawer.boundingBox())!;
    expect(bounds.x).toBeGreaterThanOrEqual(0);
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(width);
    await page.keyboard.press('Escape');
  }
});
