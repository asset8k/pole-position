import { describe, expect, it, vi } from 'vitest';
import { createApiClient } from './client';
import type { ChatResponse, ConversationDetailResponse } from './contracts';
import { createApi } from './endpoints';

function fixture(response: unknown = {}) {
  const fetch = vi.fn<typeof globalThis.fetch>().mockImplementation(async () => Response.json(response));
  return { api: createApi(createApiClient({ fetch })), fetch };
}

const token = { token: 'test-token' };

describe('typed endpoint helpers', () => {
  it('sends guest history exactly as supplied, with no conversation ID or token', async () => {
    const response: ChatResponse = { answer: 'At least two specifications. [S1]', citations: [], conversation_id: null };
    const { api, fetch } = fixture(response);
    const body = { message: 'What if they do not comply?', history: [
      { role: 'user' as const, content: 'Which tyres?' },
      { role: 'assistant' as const, content: 'At least two specifications.' },
    ] };
    expect(await api.chat.send(body)).toEqual(response);
    expect(fetch.mock.calls[0][0]).toBe('/api/chat');
    expect(JSON.parse(String(fetch.mock.calls[0][1]?.body))).toEqual(body);
    expect(new Headers(fetch.mock.calls[0][1]?.headers).has('Authorization')).toBe(false);
  });

  it('sends a registered follow-up with its ID and no injected history', async () => {
    const { api, fetch } = fixture();
    await api.chat.send({ message: 'What about penalties?', conversation_id: 2 }, token);
    expect(JSON.parse(String(fetch.mock.calls[0][1]?.body))).toEqual({ message: 'What about penalties?', conversation_id: 2 });
    expect(new Headers(fetch.mock.calls[0][1]?.headers).get('Authorization')).toBe('Bearer test-token');
  });

  it('starts a registered conversation without inventing an ID', async () => {
    const { api, fetch } = fixture({ answer: 'Answer', citations: [], conversation_id: 5 });
    expect((await api.chat.send({ message: 'Tyres?' }, token)).conversation_id).toBe(5);
    expect(JSON.parse(String(fetch.mock.calls[0][1]?.body))).toEqual({ message: 'Tyres?' });
  });

  it.each(['register', 'login'] as const)('uses JSON credentials for %s without altering the password', async (method) => {
    const { api, fetch } = fixture();
    const body = { username: 'assetk', password: '  preserve whitespace  ' };
    await api.auth[method](body);
    expect(fetch.mock.calls[0][0]).toBe(`/api/auth/${method}`);
    expect(fetch.mock.calls[0][1]?.method).toBe('POST');
    expect(JSON.parse(String(fetch.mock.calls[0][1]?.body))).toEqual(body);
    expect(new Headers(fetch.mock.calls[0][1]?.headers).has('Authorization')).toBe(false);
  });

  it('gets the current user with authentication', async () => {
    const user = { id: 1, username: 'assetk', created_at: '2026-10-05T00:00:00Z' };
    const { api, fetch } = fixture(user);
    expect(await api.auth.me(token)).toEqual(user);
    expect(fetch.mock.calls[0][0]).toBe('/api/auth/me');
    expect(new Headers(fetch.mock.calls[0][1]?.headers).get('Authorization')).toBe('Bearer test-token');
  });

  it('lists saved conversations', async () => {
    const conversations = [{ id: 2, title: 'Tyres', created_at: '2026-10-05T00:00:00Z', updated_at: '2026-10-05T00:00:00Z' }];
    const { api, fetch } = fixture(conversations);
    expect(await api.conversations.list(token)).toEqual(conversations);
    expect(fetch.mock.calls[0][0]).toBe('/api/conversations');
  });

  it('preserves messages, source metadata, and ISO timestamps when reopening a conversation', async () => {
    const detail: ConversationDetailResponse = {
      id: 2, title: 'Tyres', created_at: '2026-10-05T00:00:00Z', updated_at: '2026-10-05T00:00:00Z',
      messages: [{ id: 1, conversation_id: 2, role: 'assistant', content: 'Use two specifications. [S1]',
        created_at: '2026-10-05T00:00:00Z', citations: [{
          source_id: 'S1', chunk_id: 'document:B6.3.6:0', document_id: 'document',
          document_title: 'Sporting Regulations', section: 'B', source_kind: 'clause',
          article_identifier: 'B6', clause_identifier: 'B6.3.6', appendix_identifier: null,
          start_pdf_page: 58, end_pdf_page: 58, snippet: 'Original excerpt',
        }],
      }],
    };
    const { api, fetch } = fixture(detail);
    expect(await api.conversations.get(2, token)).toEqual(detail);
    expect(fetch.mock.calls[0][0]).toBe('/api/conversations/2');
  });

  it('renames via PATCH with only the title', async () => {
    const { api, fetch } = fixture();
    await api.conversations.rename(2, { title: 'New title' }, token);
    expect(fetch.mock.calls[0][0]).toBe('/api/conversations/2');
    expect(fetch.mock.calls[0][1]?.method).toBe('PATCH');
    expect(JSON.parse(String(fetch.mock.calls[0][1]?.body))).toEqual({ title: 'New title' });
  });

  it('deletes via DELETE and accepts the empty 204 response', async () => {
    const { api, fetch } = fixture();
    fetch.mockResolvedValueOnce(new Response(null, { status: 204 }));
    expect(await api.conversations.delete(2, token)).toBeUndefined();
    expect(fetch.mock.calls[0][0]).toBe('/api/conversations/2');
    expect(fetch.mock.calls[0][1]?.method).toBe('DELETE');
    expect(fetch.mock.calls[0][1]?.body).toBeUndefined();
  });

  it.each([0, -1, 1.5, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1])('rejects invalid conversation IDs: %s', (id) => {
    const { api, fetch } = fixture();
    expect(() => api.conversations.get(id, token)).toThrow(TypeError);
    expect(() => api.conversations.rename(id, { title: 'Title' }, token)).toThrow(TypeError);
    expect(() => api.conversations.delete(id, token)).toThrow(TypeError);
    expect(fetch).not.toHaveBeenCalled();
  });

  it('requires a non-empty token for saved data and does not fall back to guest access', () => {
    const { api, fetch } = fixture();
    expect(() => api.auth.me({ token: '' })).toThrow(TypeError);
    expect(() => api.conversations.list({ token: ' ' })).toThrow(TypeError);
    expect(() => api.conversations.get(2, { token: '' })).toThrow(TypeError);
    expect(fetch).not.toHaveBeenCalled();
  });

  it('passes cancellation to mutation requests', async () => {
    const { api, fetch } = fixture();
    const controller = new AbortController();
    await api.conversations.rename(2, { title: 'Tyres' }, { ...token, signal: controller.signal });
    expect(fetch.mock.calls[0][1]?.signal).toBe(controller.signal);
  });
});
