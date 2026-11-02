import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createApi } from './endpoints';
import { createApiClient, NetworkError, RequestTimeoutError } from './client';

function hangingFetch() {
  return vi.fn<typeof globalThis.fetch>().mockImplementation(() => new Promise(() => {}));
}

describe('bounded transport and safe-read retries', () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it.each([502, 503, 504])('retries a GET HTTP %i using 500/1000ms backoff, preserving auth', async (status) => {
    const fetch = vi.fn<typeof globalThis.fetch>()
      .mockImplementationOnce(async () => new Response('private proxy detail', { status }))
      .mockImplementationOnce(async () => new Response(null, { status }))
      .mockResolvedValueOnce(Response.json({ id: 1 }));
    const client = createApiClient({ fetch });
    const pending = client.request('/auth/me', { token: 'test-token' });
    const assertion = expect(pending).resolves.toEqual({ id: 1 });
    await vi.advanceTimersByTimeAsync(499);
    expect(fetch).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(fetch).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(999);
    expect(fetch).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1);
    await assertion;
    expect(fetch).toHaveBeenCalledTimes(3);
    for (const [, options] of fetch.mock.calls) {
      expect(options?.method).toBe('GET');
      expect(new Headers(options?.headers).get('Authorization')).toBe('Bearer test-token');
    }
    expect(vi.getTimerCount()).toBe(0);
  });

  it('caps retryable HTTP failures at three attempts and hides diagnostics', async () => {
    const fetch = vi.fn<typeof globalThis.fetch>().mockImplementation(async () =>
      Response.json({ detail: 'private credentials' }, { status: 503 }));
    const pending = createApiClient({ fetch }).request('/conversations');
    const assertion = expect(pending).rejects.toMatchObject({ status: 503,
      message: 'The server is unavailable. Please try again shortly.' });
    await vi.runAllTimersAsync();
    await assertion;
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it('recovers from network failures without exposing their diagnostics', async () => {
    const fetch = vi.fn<typeof globalThis.fetch>()
      .mockRejectedValueOnce(new TypeError('private host diagnostic'))
      .mockResolvedValueOnce(Response.json([]));
    const pending = createApiClient({ fetch }).request('/conversations');
    const assertion = expect(pending).resolves.toEqual([]);
    await vi.advanceTimersByTimeAsync(500);
    await assertion;
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it('caps persistent network failures', async () => {
    const fetch = vi.fn<typeof globalThis.fetch>().mockRejectedValue(new TypeError('private diagnostic'));
    const assertion = expect(createApiClient({ fetch }).request('/auth/me')).rejects.toBeInstanceOf(NetworkError);
    await vi.runAllTimersAsync();
    await assertion;
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it('times out even a non-cooperative fetch, retries reads, and aborts every attempt', async () => {
    const fetch = hangingFetch();
    const assertion = expect(createApiClient({ fetch, readTimeoutMs: 20 }).request('/auth/me'))
      .rejects.toBeInstanceOf(RequestTimeoutError);
    await vi.advanceTimersByTimeAsync(1_560); // 3 * 20ms + 500ms + 1000ms
    await assertion;
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(fetch.mock.calls.every(([, options]) => options?.signal?.aborted)).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('bounds response-body reads as well as connection establishment', async () => {
    const fetch = vi.fn<typeof globalThis.fetch>().mockImplementation(async () => {
      const response = Response.json({});
      vi.spyOn(response, 'text').mockImplementation(() => new Promise(() => {}));
      return response;
    });
    const assertion = expect(createApiClient({ fetch, readTimeoutMs: 20 }).request('/auth/me'))
      .rejects.toBeInstanceOf(RequestTimeoutError);
    await vi.runAllTimersAsync();
    await assertion;
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it.each([400, 401, 403, 404, 409, 422, 429, 500])('does not retry GET HTTP %i', async (status) => {
    const fetch = vi.fn<typeof globalThis.fetch>().mockResolvedValue(Response.json({}, { status }));
    await expect(createApiClient({ fetch }).request('/auth/me')).rejects.toMatchObject({ status });
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('does not retry a malformed successful response', async () => {
    const fetch = vi.fn<typeof globalThis.fetch>().mockResolvedValue(new Response('<html>wrong protocol</html>'));
    await expect(createApiClient({ fetch }).request('/auth/me')).rejects.toMatchObject({ name: 'ResponseError' });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it.each(['POST', 'PATCH', 'DELETE'] as const)('never replays %s on HTTP, network, or timeout failures', async (method) => {
    const fetch = vi.fn<typeof globalThis.fetch>().mockResolvedValue(new Response(null, { status: 503 }));
    const client = createApiClient({ fetch, mutationTimeoutMs: 30 });
    await expect(client.request('/chat', { method })).rejects.toMatchObject({ status: 503 });
    expect(fetch).toHaveBeenCalledTimes(1);
    fetch.mockReset().mockRejectedValue(new TypeError('private'));
    await expect(client.request('/chat', { method })).rejects.toBeInstanceOf(NetworkError);
    expect(fetch).toHaveBeenCalledTimes(1);
    fetch.mockReset().mockImplementation(() => new Promise(() => {}));
    const assertion = expect(client.request('/chat', { method })).rejects.toBeInstanceOf(RequestTimeoutError);
    await vi.advanceTimersByTimeAsync(30);
    await assertion;
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('does not retry GET requests carrying a body', async () => {
    const fetch = vi.fn<typeof globalThis.fetch>().mockRejectedValue(new TypeError('GET body rejected'));
    await expect(createApiClient({ fetch }).request('/chat', { body: {} })).rejects.toBeInstanceOf(NetworkError);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('never retries actual chat generation, login, registration, rename, or delete endpoints', async () => {
    const fetch = vi.fn<typeof globalThis.fetch>().mockImplementation(async () => new Response(null, { status: 502 }));
    const api = createApi(createApiClient({ fetch }));
    const options = { token: 'test-token' };
    for (const action of [
      () => api.chat.send({ message: 'Tyres?' }),
      () => api.auth.login({ username: 'assetk', password: 'test-only-password' }),
      () => api.auth.register({ username: 'assetk', password: 'test-only-password' }),
      () => api.conversations.rename(1, { title: 'New title' }, options),
      () => api.conversations.delete(1, options),
    ]) {
      fetch.mockClear();
      await expect(action()).rejects.toMatchObject({ status: 502 });
      expect(fetch).toHaveBeenCalledTimes(1);
    }
  });

  it('does not start already-cancelled requests', async () => {
    const fetch = hangingFetch();
    const controller = new AbortController();
    controller.abort();
    await expect(createApiClient({ fetch }).request('/auth/me', { signal: controller.signal }))
      .rejects.toMatchObject({ name: 'AbortError' });
    expect(fetch).not.toHaveBeenCalled();
  });

  it('cancels an in-flight fetch and clears its timeout without retrying', async () => {
    const fetch = hangingFetch();
    const controller = new AbortController();
    const assertion = expect(createApiClient({ fetch }).request('/auth/me', { signal: controller.signal }))
      .rejects.toMatchObject({ name: 'AbortError' });
    controller.abort();
    await assertion;
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][1]?.signal?.aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('cancels during backoff without another request', async () => {
    const fetch = vi.fn<typeof globalThis.fetch>().mockRejectedValue(new TypeError('offline'));
    const controller = new AbortController();
    const assertion = expect(createApiClient({ fetch }).request('/auth/me', { signal: controller.signal }))
      .rejects.toMatchObject({ name: 'AbortError' });
    await vi.advanceTimersByTimeAsync(0);
    expect(fetch).toHaveBeenCalledTimes(1);
    controller.abort();
    await assertion;
    await vi.runAllTimersAsync();
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each([0, -1, Infinity, NaN])('rejects an unbounded/invalid timeout: %s', (timeout) => {
    expect(() => createApiClient({ readTimeoutMs: timeout })).toThrow(TypeError);
    expect(() => createApiClient({ mutationTimeoutMs: timeout })).toThrow(TypeError);
  });
});
