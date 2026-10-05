import assert from 'node:assert/strict';
import test from 'node:test';
import { runSmoke } from '../../scripts/live-smoke.mjs';

test('default is read-only health, never chat', async () => {
  const calls = [];
  await runSmoke({ log() {}, fetcher: async (url) => { calls.push(url); return Response.json({ status: 'ok' }); } });
  assert.deepEqual(calls, ['http://127.0.0.1:8000/api/health']);
});

test('explicit chat sends one anonymous question and checks its citation', async () => {
  const calls = [];
  await runSmoke({ chat: true, log() {}, fetcher: async (url, options) => {
    calls.push([url, options]);
    return Response.json(url.endsWith('/health') ? { status: 'ok' } : {
      answer: 'Right-handed Cartesian system. [S1]', conversation_id: null,
      citations: [{ source_id: 'S1', section: 'C', clause_identifier: 'C2.1.1', snippet: 'Coordinate system', start_pdf_page: 9, end_pdf_page: 9 }],
    });
  } });
  assert.equal(calls.length, 2);
  assert.deepEqual(calls[1][1].headers, { 'Content-Type': 'application/json' });
  const body = JSON.parse(calls[1][1].body);
  assert.deepEqual(body.history, []);
  assert.equal(body.conversation_id, undefined);
});

test('failed health never attempts chat', async () => {
  let calls = 0;
  await assert.rejects(runSmoke({ chat: true, log() {}, fetcher: async () => { calls++; return new Response(null, { status: 503 }); } }), /503/);
  assert.equal(calls, 1);
});

test('a saved response or invalid citation fails instead of claiming success', async () => {
  for (const result of [
    { answer: 'Answer', citations: [], conversation_id: 1 },
    { answer: 'Answer', citations: [], conversation_id: null },
    { answer: 'Answer [S1]', citations: [{ source_id: 'S1', section: 'C', clause_identifier: 'C2.1.1', snippet: '', start_pdf_page: 0, end_pdf_page: 0 }], conversation_id: null },
  ]) {
    await assert.rejects(runSmoke({ chat: true, log() {}, fetcher: async (url) => Response.json(url.endsWith('/health') ? { status: 'ok' } : result) }));
  }
});
