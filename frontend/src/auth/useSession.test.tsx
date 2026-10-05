import { StrictMode } from 'react';
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, NetworkError } from '../api/client';
import { api } from '../api/endpoints';
import { SESSION_STORAGE_KEY, reportUnauthorized } from './sessionEvents';
import { AccountCreatedError, tokenExpiry, useSession } from './useSession';

const user = { id: 1, username: 'assetk', created_at: '2026-10-05T12:00:00Z' };
const credentials = { username: 'assetk', password: 'securepassword123' };
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((accept) => { resolve = accept; });
  return { promise, resolve };
}
beforeEach(() => {
  sessionStorage.removeItem(SESSION_STORAGE_KEY);
  vi.spyOn(api.auth, 'me').mockResolvedValue(user);
  vi.spyOn(api.auth, 'register').mockResolvedValue(user);
  vi.spyOn(api.auth, 'login').mockResolvedValue({ access_token: 'valid-token', token_type: 'bearer' });
});
afterEach(() => { sessionStorage.removeItem(SESSION_STORAGE_KEY); vi.restoreAllMocks(); vi.useRealTimers(); });

describe('session lifecycle', () => {
  it('starts as guest without making authentication requests', () => {
    const { result } = renderHook(useSession);
    expect(result.current.status).toBe('guest');
    expect(api.auth.me).not.toHaveBeenCalled();
  });

  it('verifies a login before storing only its token', async () => {
    const { result } = renderHook(useSession);
    await act(async () => { await result.current.authenticate('login', credentials); });
    expect(api.auth.login).toHaveBeenCalledWith(credentials, { signal: expect.any(AbortSignal) });
    expect(api.auth.me).toHaveBeenCalledWith({ token: 'valid-token', signal: expect.any(AbortSignal) });
    expect(result.current.user).toEqual(user);
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBe('valid-token');
    expect(JSON.stringify(sessionStorage)).not.toContain(credentials.password);
  });

  it('restores a tab session with /me rather than trusting decoded identity', async () => {
    sessionStorage.setItem(SESSION_STORAGE_KEY, 'stored-token');
    const pending = deferred<typeof user>();
    vi.mocked(api.auth.me).mockReturnValue(pending.promise);
    const { result } = renderHook(useSession);
    expect(result.current.status).toBe('restoring');
    expect(result.current.user).toBeNull();
    await act(async () => { pending.resolve(user); });
    expect(result.current.status).toBe('authenticated');
    expect(result.current.token).toBe('stored-token');
  });

  it('handles StrictMode restore cancellation and installs the surviving request only', async () => {
    sessionStorage.setItem(SESSION_STORAGE_KEY, 'stored-token');
    const { result } = renderHook(useSession, { wrapper: StrictMode });
    await waitFor(() => expect(result.current.status).toBe('authenticated'));
    const calls = vi.mocked(api.auth.me).mock.calls;
    expect(calls[0][0].signal?.aborted).toBe(true);
  });

  it('clears expired restoration tokens but preserves unrelated storage', async () => {
    sessionStorage.setItem(SESSION_STORAGE_KEY, 'expired');
    sessionStorage.setItem('unrelated', 'keep');
    vi.mocked(api.auth.me).mockRejectedValue(new ApiError(401, 'Invalid token'));
    const { result } = renderHook(useSession);
    await waitFor(() => expect(result.current.status).toBe('guest'));
    expect(result.current.notice).toContain('expired');
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
    expect(sessionStorage.getItem('unrelated')).toBe('keep');
    sessionStorage.removeItem('unrelated');
  });

  it('keeps a stored token on transient verification failure and supports retry', async () => {
    sessionStorage.setItem(SESSION_STORAGE_KEY, 'stored-token');
    vi.mocked(api.auth.me).mockRejectedValueOnce(new NetworkError());
    const { result } = renderHook(useSession);
    await waitFor(() => expect(result.current.status).toBe('unavailable'));
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBe('stored-token');
    await act(async () => { await result.current.restore(); });
    expect(result.current.status).toBe('authenticated');
  });

  it('supports continue-as-guest after verification failure', async () => {
    sessionStorage.setItem(SESSION_STORAGE_KEY, 'stored-token');
    vi.mocked(api.auth.me).mockRejectedValueOnce(new NetworkError());
    const { result } = renderHook(useSession);
    await waitFor(() => expect(result.current.status).toBe('unavailable'));
    act(() => result.current.logout());
    expect(result.current.status).toBe('guest');
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
  });

  it('never installs late login or restoration responses after cancellation/logout', async () => {
    const pending = deferred<typeof user>();
    vi.mocked(api.auth.me).mockReturnValue(pending.promise);
    const { result } = renderHook(useSession);
    let task!: Promise<void>;
    await act(async () => { task = result.current.authenticate('login', credentials); });
    act(() => result.current.logout());
    await act(async () => { pending.resolve(user); await task; });
    expect(result.current.status).toBe('guest');
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
  });

  it('registers, logs in, and verifies without persisting credentials', async () => {
    const { result } = renderHook(useSession);
    await act(async () => { await result.current.authenticate('register', credentials); });
    expect(api.auth.register).toHaveBeenCalledOnce();
    expect(api.auth.login).toHaveBeenCalledOnce();
    expect(result.current.status).toBe('authenticated');
  });

  it('distinguishes successful registration followed by login failure', async () => {
    vi.mocked(api.auth.login).mockRejectedValue(new NetworkError());
    const { result } = renderHook(useSession);
    await act(async () => {
      await expect(result.current.authenticate('register', credentials)).rejects.toBeInstanceOf(AccountCreatedError);
    });
    expect(result.current.status).toBe('guest');
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
  });

  it('invalidates only the current token when a protected request gets 401', async () => {
    const { result } = renderHook(useSession);
    await act(async () => { await result.current.authenticate('login', credentials); });
    act(() => reportUnauthorized('old-token'));
    expect(result.current.status).toBe('authenticated');
    act(() => reportUnauthorized('valid-token'));
    expect(result.current.status).toBe('guest');
    expect(result.current.notice).toContain('expired');
  });

  it('expires verified JWT sessions by time even without another request', async () => {
    vi.useFakeTimers();
    const token = `header.${btoa(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + 10 }))}.signature`;
    vi.mocked(api.auth.login).mockResolvedValue({ access_token: token, token_type: 'bearer' });
    const { result } = renderHook(useSession);
    await act(async () => { await result.current.authenticate('login', credentials); });
    expect(result.current.status).toBe('authenticated');
    await act(async () => { vi.advanceTimersByTime(11_000); });
    expect(result.current.status).toBe('guest');
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
  });

  it('uses page-only authentication if storage is unavailable', async () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('Blocked'); });
    const { result } = renderHook(useSession);
    await act(async () => { await result.current.authenticate('login', credentials); });
    expect(result.current.status).toBe('authenticated');
    expect(result.current.notice).toContain('page only');
  });

  it('rejects malformed identity and token responses', async () => {
    vi.mocked(api.auth.me).mockResolvedValue({ ...user, id: -1 });
    const { result } = renderHook(useSession);
    await act(async () => {
      await expect(result.current.authenticate('login', credentials)).rejects.toMatchObject({ name: 'ResponseError' });
    });
    expect(result.current.status).toBe('guest');
    vi.mocked(api.auth.login).mockResolvedValue({ access_token: '', token_type: 'bearer' });
    await act(async () => {
      await expect(result.current.authenticate('login', credentials)).rejects.toMatchObject({ name: 'ResponseError' });
    });
  });
});

it('JWT expiry parsing is optional and never establishes identity', () => {
  expect(tokenExpiry('opaque')).toBeNull();
  expect(tokenExpiry('a.invalid.c')).toBeNull();
  expect(tokenExpiry(`a.${btoa('{"exp":"invalid"}')}.c`)).toBeNull();
  expect(tokenExpiry(`a.${btoa('{"exp":123}')}.c`)).toBe(123000);
});
