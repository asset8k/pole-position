import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, NetworkError, ResponseError } from '../api/client';
import type { LoginRequest, UserResponse } from '../api/contracts';
import { api } from '../api/endpoints';
import { SESSION_STORAGE_KEY, SESSION_UNAUTHORIZED } from './sessionEvents';

export type AuthMode = 'login' | 'register';
type SessionState =
  | { status: 'guest' | 'restoring' | 'unavailable'; token: null; user: null }
  | { status: 'authenticated'; token: string; user: UserResponse };
const guest: SessionState = { status: 'guest', token: null, user: null };

function storedToken(): string | null {
  try { return sessionStorage.getItem(SESSION_STORAGE_KEY)?.trim() || null; }
  catch { return null; }
}

function storeToken(token: string | null): boolean {
  try {
    if (token) sessionStorage.setItem(SESSION_STORAGE_KEY, token);
    else sessionStorage.removeItem(SESSION_STORAGE_KEY);
    return true;
  } catch { return false; }
}

function validateUser(value: unknown): asserts value is UserResponse {
  if (typeof value !== 'object' || value === null || !('id' in value)
      || !Number.isSafeInteger(value.id) || Number(value.id) <= 0
      || !('username' in value) || typeof value.username !== 'string'
      || !/^[a-z0-9_]{3,50}$/.test(value.username)
      || !('created_at' in value) || typeof value.created_at !== 'string'
      || !Number.isFinite(Date.parse(value.created_at))) throw new ResponseError(200);
}

// Reading exp is only for early UI cleanup. /auth/me verifies the actual JWT;
// unverified claims never establish identity or authorize a request.
export function tokenExpiry(token: string): number | null {
  try {
    const encoded = token.split('.')[1];
    if (!encoded) return null;
    const normalized = encoded.replace(/-/g, '+').replace(/_/g, '/');
    const data: unknown = JSON.parse(atob(normalized.padEnd(Math.ceil(normalized.length / 4) * 4, '=')));
    if (typeof data === 'object' && data !== null && 'exp' in data
        && typeof data.exp === 'number' && Number.isFinite(data.exp)) return data.exp * 1000;
  } catch { /* An opaque token is still verified by the backend. */ }
  return null;
}

export class AccountCreatedError extends Error {
  constructor() { super('Account created. Please sign in to continue.'); }
}

export function authErrorMessage(error: unknown): string {
  if (error instanceof AccountCreatedError) return error.message;
  if (error instanceof ApiError) {
    if (error.status === 401) return 'Incorrect username or password.';
    if (error.status === 409) return 'That username is already taken.';
    if (error.status === 422) return 'Check your username and password requirements.';
  }
  if (error instanceof ApiError || error instanceof NetworkError || error instanceof ResponseError) return error.message;
  return 'Unable to sign in. Please try again.';
}

export function useSession() {
  const [state, setState] = useState<SessionState>(() => storedToken()
    ? { status: 'restoring', token: null, user: null } : guest);
  const [notice, setNotice] = useState('');
  const currentToken = useRef<string | null>(null);
  const requestRef = useRef<AbortController | null>(null);

  const cancelRequest = useCallback(() => {
    const request = requestRef.current;
    requestRef.current = null;
    request?.abort();
  }, []);

  const logout = useCallback((message = '') => {
    cancelRequest();
    currentToken.current = null;
    const removed = storeToken(null);
    setState(guest);
    setNotice(removed ? message : 'Signed out in this page. Browser storage is unavailable; close this tab to clear its stored session.');
  }, [cancelRequest]);

  const install = useCallback((token: string, user: UserResponse) => {
    validateUser(user);
    const expiry = tokenExpiry(token);
    if (expiry !== null && expiry <= Date.now()) throw new ApiError(401, 'Session expired.');
    currentToken.current = token;
    const saved = storeToken(token);
    setState({ status: 'authenticated', token, user });
    setNotice(saved ? '' : 'Signed in for this page only. Browser storage is unavailable.');
  }, []);

  const restore = useCallback(async () => {
    cancelRequest();
    const token = storedToken();
    if (!token) { setState(guest); return; }
    const request = new AbortController();
    requestRef.current = request;
    currentToken.current = token;
    setState({ status: 'restoring', token: null, user: null });
    setNotice('');
    try {
      const user = await api.auth.me({ token, signal: request.signal });
      if (requestRef.current === request) install(token, user);
    } catch (error) {
      if (requestRef.current !== request) return;
      if (error instanceof ApiError && error.status === 401) logout('Your session expired. Please sign in again.');
      else {
        setState({ status: 'unavailable', token: null, user: null });
        setNotice('Unable to verify your session. Retry, or continue as a guest.');
      }
    } finally {
      if (requestRef.current === request) requestRef.current = null;
    }
  }, [cancelRequest, install, logout]);

  useEffect(() => { void restore(); return cancelRequest; }, [restore, cancelRequest]);

  useEffect(() => {
    function unauthorized(event: Event) {
      if (event instanceof CustomEvent && event.detail === currentToken.current && currentToken.current) {
        logout('Your session expired. Please sign in again.');
      }
    }
    window.addEventListener(SESSION_UNAUTHORIZED, unauthorized);
    return () => window.removeEventListener(SESSION_UNAUTHORIZED, unauthorized);
  }, [logout]);

  useEffect(() => {
    if (!state.token) return;
    const expiry = tokenExpiry(state.token);
    if (expiry === null) return;
    let timer: ReturnType<typeof setTimeout>;
    function checkExpiry() {
      clearTimeout(timer);
      const remaining = expiry! - Date.now();
      if (remaining <= 0) logout('Your session expired. Please sign in again.');
      else timer = setTimeout(checkExpiry, Math.min(remaining, 2_147_483_647));
    }
    checkExpiry();
    window.addEventListener('focus', checkExpiry);
    return () => { clearTimeout(timer); window.removeEventListener('focus', checkExpiry); };
  }, [state.token, logout]);

  const authenticate = useCallback(async (mode: AuthMode, credentials: LoginRequest) => {
    cancelRequest();
    const request = new AbortController();
    requestRef.current = request;
    let accountCreated = false;
    try {
      if (mode === 'register') {
        const user = await api.auth.register(credentials, { signal: request.signal });
        validateUser(user);
        accountCreated = true;
      }
      if (requestRef.current !== request) return;
      const result = await api.auth.login(credentials, { signal: request.signal });
      if (!result || typeof result.access_token !== 'string' || !result.access_token.trim()
          || result.token_type?.toLowerCase() !== 'bearer') throw new ResponseError(200);
      if (requestRef.current !== request) return;
      const user = await api.auth.me({ token: result.access_token, signal: request.signal });
      if (requestRef.current === request) install(result.access_token, user);
    } catch (error) {
      if (requestRef.current !== request) return;
      if (accountCreated) throw new AccountCreatedError();
      throw error;
    } finally {
      if (requestRef.current === request) requestRef.current = null;
    }
  }, [cancelRequest, install]);

  return { ...state, notice, authenticate, cancelAuthentication: cancelRequest, logout, restore };
}

export type Session = ReturnType<typeof useSession>;
