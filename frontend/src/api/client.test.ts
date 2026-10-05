import { describe, expect, it, vi } from 'vitest';
import { ApiError, createApiClient, NetworkError, ResponseError } from './client';

function mockClient(response: Response) {
  const fetch = vi.fn<typeof globalThis.fetch>().mockResolvedValue(response);
  return { client: createApiClient({ fetch }), fetch };
}

describe('JSON API client', () => {
  it('reports unauthorized only for protected requests, with the failing token identity', async () => {
    const onUnauthorized = vi.fn();
    const fetch = vi.fn<typeof globalThis.fetch>().mockImplementation(async () => Response.json({}, { status: 401 }));
    const client = createApiClient({ fetch, onUnauthorized });
    await expect(client.request('/auth/login', { method: 'POST' })).rejects.toBeInstanceOf(ApiError);
    expect(onUnauthorized).not.toHaveBeenCalled();
    await expect(client.request('/chat', { token: 'expired-token' })).rejects.toBeInstanceOf(ApiError);
    expect(onUnauthorized).toHaveBeenCalledExactlyOnceWith('expired-token');
  });
  it('uses same-origin JSON requests without cookies or guest authorization', async () => {
    const { client, fetch } = mockClient(Response.json({ answer: 'Hello' }));
    expect(await client.request('/chat', { method: 'POST', body: { message: 'Tyres?' } }))
      .toEqual({ answer: 'Hello' });
    const [url, options] = fetch.mock.calls[0];
    expect(url).toBe('/api/chat');
    expect(options).toMatchObject({ method: 'POST', body: '{"message":"Tyres?"}', credentials: 'omit' });
    const headers = new Headers(options?.headers);
    expect(headers.get('Accept')).toBe('application/json');
    expect(headers.get('Content-Type')).toBe('application/json');
    expect(headers.has('Authorization')).toBe(false);
  });

  it('passes a bearer token and AbortSignal without setting a body on GET', async () => {
    const { client, fetch } = mockClient(Response.json({ id: 1 }));
    const controller = new AbortController();
    await client.request('/auth/me', { token: 'test-token', signal: controller.signal });
    const options = fetch.mock.calls[0][1];
    expect(options?.signal).toBe(controller.signal);
    expect(options?.body).toBeUndefined();
    expect(new Headers(options?.headers).get('Authorization')).toBe('Bearer test-token');
    expect(new Headers(options?.headers).has('Content-Type')).toBe(false);
  });

  it('parses a 201 JSON response', async () => {
    const { client } = mockClient(Response.json({ id: 2 }, { status: 201 }));
    expect(await client.request('/auth/register', { method: 'POST' })).toEqual({ id: 2 });
  });

  it('returns undefined on 204 without reading or parsing its empty body', async () => {
    const response = new Response(null, { status: 204 });
    const text = vi.spyOn(response, 'text');
    const { client } = mockClient(response);
    expect(await client.request<void>('/conversations/1', { method: 'DELETE' })).toBeUndefined();
    expect(text).not.toHaveBeenCalled();
  });

  it('accepts vendor JSON content types', async () => {
    const { client } = mockClient(new Response('{"ok":true}', {
      headers: { 'Content-Type': 'application/example+json; charset=utf-8' },
    }));
    expect(await client.request('/chat')).toEqual({ ok: true });
  });

  it.each([
    ['HTML', '<html>Proxy error</html>', 'text/html'],
    ['malformed JSON', '{broken', 'application/json'],
    ['empty JSON', '', 'application/json'],
  ])('rejects a successful %s response as a protocol error', async (_name, body, contentType) => {
    const { client } = mockClient(new Response(body, { headers: { 'Content-Type': contentType } }));
    await expect(client.request('/chat')).rejects.toMatchObject({ name: 'ResponseError', status: 200 });
  });

  it.each([
    [401, 'Incorrect username or password'],
    [404, 'Conversation not found'],
    [409, 'Username already exists'],
    [422, 'Authenticated requests must omit client-supplied history'],
  ])('preserves an HTTP %i user-facing detail', async (status, detail) => {
    const { client } = mockClient(Response.json({ detail }, { status }));
    await expect(client.request('/auth/login')).rejects.toMatchObject({ name: 'ApiError', status, message: detail });
  });

  it('extracts validation fields but discards sensitive inputs and context', async () => {
    const { client } = mockClient(Response.json({ detail: [{
      loc: ['body', 'password'], msg: 'String should have at least 8 characters',
      type: 'string_too_short', input: 'secret', ctx: { min_length: 8, password: 'secret' },
    }] }, { status: 422 }));
    const error: unknown = await client.request('/auth/register').catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    if (!(error instanceof ApiError)) throw new Error('Expected ApiError');
    expect(error.issues).toEqual([{
      location: ['body', 'password'], message: 'String should have at least 8 characters', type: 'string_too_short',
    }]);
    expect(JSON.stringify(error)).not.toContain('secret');
    expect(error.message).toBe('Please check the information you entered.');
  });

  it('tolerates malformed validation details', async () => {
    const { client } = mockClient(Response.json({ detail: [null, 'bad', { loc: ['body', 0, {}] }] }, { status: 422 }));
    await expect(client.request('/chat')).rejects.toMatchObject({ issues: [
      { location: ['body', 0], message: 'Invalid value', type: 'validation_error' },
    ] });
  });

  it.each([
    new Response('<html>Internal stack trace</html>', { status: 502 }),
    Response.json({ detail: 'Database password: sensitive' }, { status: 500 }),
    new Response('{broken', { status: 503, headers: { 'Content-Type': 'application/json' } }),
  ])('does not expose server internals for upstream failures', async (response) => {
    const { client } = mockClient(response);
    await expect(client.request('/chat')).rejects.toMatchObject({
      name: 'ApiError', status: response.status,
      message: 'The server is unavailable. Please try again shortly.',
    });
  });

  it('handles a rate limit without retrying', async () => {
    const { client, fetch } = mockClient(Response.json({ detail: 'Slow down' }, { status: 429 }));
    await expect(client.request('/chat', { method: 'POST', body: {} })).rejects.toMatchObject({ status: 429 });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('reports network failures without leaking raw errors or retrying', async () => {
    const fetch = vi.fn<typeof globalThis.fetch>().mockRejectedValue(new TypeError('private diagnostic'));
    const client = createApiClient({ fetch });
    await expect(client.request('/chat', { method: 'POST' })).rejects.toBeInstanceOf(NetworkError);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('reports a broken response stream as a network failure', async () => {
    const response = Response.json({});
    vi.spyOn(response, 'text').mockRejectedValue(new TypeError('Connection lost'));
    const { client } = mockClient(response);
    await expect(client.request('/chat')).rejects.toBeInstanceOf(NetworkError);
  });

  it('preserves aborts so cancelled requests are not displayed as network errors', async () => {
    const error = new DOMException('Aborted', 'AbortError');
    const fetch = vi.fn<typeof globalThis.fetch>().mockRejectedValue(error);
    await expect(createApiClient({ fetch }).request('/chat')).rejects.toBe(error);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('normalizes a configured base URL', async () => {
    const fetch = vi.fn<typeof globalThis.fetch>().mockResolvedValue(Response.json({}));
    await createApiClient({ fetch, baseUrl: 'https://api.example.test/api/' }).request('/chat');
    expect(fetch.mock.calls[0][0]).toBe('https://api.example.test/api/chat');
  });

  it.each(['//other.test/api', 'javascript:alert(1)', '/api?token=secret', '/api#fragment', 'https://user:pass@example.test'])
    ('rejects an unsafe base URL: %s', (baseUrl) => {
      expect(() => createApiClient({ baseUrl })).toThrow(TypeError);
    });

  it('rejects an absolute endpoint without making a request', async () => {
    const { client, fetch } = mockClient(Response.json({}));
    await expect(client.request('https://other.test/chat')).rejects.toThrow(TypeError);
    expect(fetch).not.toHaveBeenCalled();
  });

  it('exposes distinct error classes for future UI handling', () => {
    expect(new ApiError(401, 'Sign in')).toBeInstanceOf(Error);
    expect(new NetworkError().name).toBe('NetworkError');
    expect(new ResponseError(200).name).toBe('ResponseError');
  });
});
