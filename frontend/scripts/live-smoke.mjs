// Read-only health check by default. --chat explicitly opts into one paid guest
// generation request. No token, registration, saved conversation, or DB mutation.
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';

const base = 'http://127.0.0.1:8000';
export async function runSmoke({ chat = false, fetcher = fetch, log = console.log } = {}) {
  async function request(path, options = {}) {
    const response = await fetcher(`${base}${path}`, { ...options, signal: AbortSignal.timeout(path === '/api/chat' ? 180_000 : 5_000) });
    assert(response.ok, `${path} returned HTTP ${response.status}`);
    return response.json();
  }
  const health = await request('/api/health');
  assert.equal(health.status, 'ok');
  log('Live backend health passed.');
  if (chat) {
    const result = await request('/api/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: 'How is the F1 car coordinate system defined?', history: [] }),
    });
    assert.equal(result.conversation_id, null, 'Guest response must not create a saved conversation.');
    assert.equal(typeof result.answer, 'string');
    assert(result.answer.trim());
    assert(Array.isArray(result.citations));
    const cited = result.citations.find((source) => source.section === 'C' && source.clause_identifier === 'C2.1.1');
    assert(cited, 'Expected coordinate-system source C2.1.1.');
    assert(result.answer.includes(`[${cited.source_id}]`), 'Expected an inline marker for the returned source.');
    for (const source of result.citations) {
      assert.equal(typeof source.snippet, 'string');
      assert(source.snippet.trim());
      assert(Number.isInteger(source.start_pdf_page) && source.start_pdf_page > 0);
      assert(Number.isInteger(source.end_pdf_page) && source.end_pdf_page >= source.start_pdf_page);
    }
    log('One live guest chat passed: grounded source, usable citation metadata, no saved conversation.');
    log('This is a smoke check, not an answer-quality evaluation.');
  } else log('Chat was not called. Use --chat only when you want a paid guest-generation smoke check.');
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const args = process.argv.slice(2);
    assert(args.every((argument) => argument === '--chat'), 'Only --chat is supported.');
    await runSmoke({ chat: args.includes('--chat') });
  } catch (error) {
    // Do not print environment values, tokens or server diagnostics.
    console.error(error instanceof assert.AssertionError ? error.message : 'Live backend unavailable or the request failed. Start FastAPI on 127.0.0.1:8000 and retry.');
    process.exitCode = 1;
  }
}
