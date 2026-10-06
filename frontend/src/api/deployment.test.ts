import { afterEach, expect, it, vi } from 'vitest';

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.resetModules();
});

it.each([
  ['', '/api/chat'],
  ['https://pole-position.fastapicloud.dev/api', 'https://pole-position.fastapicloud.dev/api/chat'],
])('uses the configured API base URL without losing the API prefix', async (baseUrl, expected) => {
  vi.stubEnv('VITE_API_BASE_URL', baseUrl);
  const fetch = vi.fn().mockResolvedValue(Response.json({ answer: 'Answer', citations: [], conversation_id: null }));
  vi.stubGlobal('fetch', fetch);
  vi.resetModules();
  const { api } = await import('./endpoints');
  await api.chat.send({ message: 'Tyres?' });
  expect(fetch.mock.calls[0][0]).toBe(expected);
});
