export interface ValidationIssue {
  location: (string | number)[];
  message: string;
  type: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly issues: ValidationIssue[];

  constructor(status: number, message: string, issues: ValidationIssue[] = []) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.issues = issues;
  }
}

export class NetworkError extends Error {
  constructor() {
    super('Unable to reach the server. Check your connection and try again.');
    this.name = 'NetworkError';
  }
}

export class RequestTimeoutError extends NetworkError {
  constructor() {
    super();
    this.name = 'RequestTimeoutError';
    this.message = 'The server took too long to respond. Please try again shortly.';
  }
}

export class ResponseError extends Error {
  constructor(readonly status: number) {
    super('The server returned an unexpected response. Please try again.');
    this.name = 'ResponseError';
  }
}

export interface RequestOptions {
  token?: string;
  signal?: AbortSignal;
}

interface JsonRequestOptions extends RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
  body?: unknown;
}

export interface ApiClientOptions {
  baseUrl?: string;
  fetch?: typeof globalThis.fetch;
  onUnauthorized?: (token: string) => void;
  readTimeoutMs?: number;
  mutationTimeoutMs?: number;
}

const READ_TIMEOUT_MS = 15_000;
const MUTATION_TIMEOUT_MS = 180_000; // Chat includes retrieval, reranking, and generation.
const READ_RETRIES = 2;
const RETRY_DELAY_MS = 500;
const RETRY_STATUSES = new Set([502, 503, 504]);

function abortReason(signal: AbortSignal): unknown {
  return signal.reason ?? new DOMException('Aborted', 'AbortError');
}

async function withDeadline<T>(
  operation: (signal: AbortSignal) => Promise<T>, timeoutMs: number, signal?: AbortSignal,
): Promise<T> {
  if (signal?.aborted) throw abortReason(signal);
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout>;
  let onAbort: () => void;
  const interrupted = new Promise<never>((_resolve, reject) => {
    onAbort = () => {
      reject(abortReason(signal!));
      controller.abort();
    };
    signal?.addEventListener('abort', onAbort, { once: true });
    timer = setTimeout(() => {
      reject(new RequestTimeoutError());
      controller.abort();
    }, timeoutMs);
  });
  try {
    // The race also bounds response-body reads and non-cooperative fetch mocks.
    return await Promise.race([interrupted, operation(controller.signal)]);
  } finally {
    clearTimeout(timer!);
    signal?.removeEventListener('abort', onAbort!);
  }
}

async function retryDelay(milliseconds: number, signal?: AbortSignal): Promise<void> {
  if (signal?.aborted) throw abortReason(signal);
  return new Promise((resolve, reject) => {
    const onAbort = () => {
      clearTimeout(timer);
      signal?.removeEventListener('abort', onAbort);
      reject(abortReason(signal!));
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, milliseconds);
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function httpError(status: number, data: unknown): ApiError {
  const detail = isRecord(data) ? data.detail : undefined;
  // FastAPI validation errors may include passwords under `input`/`ctx`.
  // Retain only the fields needed to display a useful validation message.
  const issues: ValidationIssue[] = Array.isArray(detail)
    ? detail.filter(isRecord).map((issue) => ({
        location: Array.isArray(issue.loc)
          ? issue.loc.filter((part): part is string | number =>
              typeof part === 'string' || typeof part === 'number')
          : [],
        message: typeof issue.msg === 'string' ? issue.msg : 'Invalid value',
        type: typeof issue.type === 'string' ? issue.type : 'validation_error',
      }))
    : [];

  let message = 'The request could not be completed. Please try again.';
  if (status >= 500) message = 'The server is unavailable. Please try again shortly.';
  else if (status === 401) message = 'Please sign in again to continue.';
  else if (status === 403) message = 'You do not have permission to do that.';
  else if (status === 404) message = 'The requested item was not found.';
  else if (status === 422) message = 'Please check the information you entered.';
  else if (status === 429) message = 'Too many requests. Please wait and try again.';

  if ([400, 401, 403, 404, 409, 422].includes(status)
      && typeof detail === 'string' && detail.trim()) {
    message = detail.slice(0, 300);
  }
  return new ApiError(status, message, issues);
}

function isAbort(error: unknown): boolean {
  // DOMExceptions may originate in another realm and fail instanceof Error.
  return isRecord(error) && error.name === 'AbortError';
}

export function createApiClient(options: ApiClientOptions = {}) {
  const readTimeoutMs = options.readTimeoutMs ?? READ_TIMEOUT_MS;
  const mutationTimeoutMs = options.mutationTimeoutMs ?? MUTATION_TIMEOUT_MS;
  if (![readTimeoutMs, mutationTimeoutMs].every((value) => Number.isFinite(value) && value > 0)) {
    throw new TypeError('Request timeouts must be positive finite milliseconds.');
  }
  const baseUrl = (options.baseUrl ?? '/api').replace(/\/+$/, '');
  // Same-origin by default; an explicitly configured HTTP(S) API is also allowed.
  if (!/^\/(?!\/)/.test(baseUrl) && !/^https?:\/\//.test(baseUrl)) {
    throw new TypeError('API base URL must be an absolute HTTP(S) URL or a root-relative path.');
  }
  if (/[?#]/.test(baseUrl)) throw new TypeError('API base URL must not contain a query or fragment.');
  if (/^https?:/.test(baseUrl)) {
    const url = new URL(baseUrl);
    if (url.username || url.password) throw new TypeError('API base URL must not contain credentials.');
  }

  async function request<T>(path: string, requestOptions: JsonRequestOptions = {}): Promise<T> {
    if (!path.startsWith('/') || path.startsWith('//')) {
      throw new TypeError('API endpoint must be a root-relative path.');
    }
    const headers = new Headers({ Accept: 'application/json' });
    if (requestOptions.body !== undefined) headers.set('Content-Type', 'application/json');
    if (requestOptions.token) headers.set('Authorization', `Bearer ${requestOptions.token}`);
    const body = requestOptions.body === undefined ? undefined : JSON.stringify(requestOptions.body);

    const method = requestOptions.method ?? 'GET';
    const safeRead = method === 'GET' && body === undefined;

    async function send() {
      for (let attempt = 0; ; attempt += 1) {
        const canRetry = safeRead && attempt < READ_RETRIES;
        try {
          const result = await withDeadline(async (signal) => {
            const response = await (options.fetch ?? globalThis.fetch)(`${baseUrl}${path}`, {
              method, headers, body, signal, credentials: 'omit',
            });
            if (canRetry && RETRY_STATUSES.has(response.status)) {
              // Discard retryable error bodies without parsing private diagnostics.
              void response.body?.cancel().catch(() => undefined);
              return { response, text: '' };
            }
            return { response, text: response.status === 204 ? '' : await response.text() };
          }, safeRead ? readTimeoutMs : mutationTimeoutMs, requestOptions.signal);
          if (!canRetry || !RETRY_STATUSES.has(result.response.status)) return result;
        } catch (error) {
          // User cancellation never retries; a deadline is a recoverable failure.
          if (isAbort(error) || requestOptions.signal?.aborted) throw error;
          if (!canRetry) throw error instanceof RequestTimeoutError ? error : new NetworkError();
        }
        // Only GET without a body can reach this backoff. Never replay mutations.
        await retryDelay(RETRY_DELAY_MS * 2 ** attempt, requestOptions.signal);
      }
    }

    const { response, text } = await send();
    if (response.status === 204) return undefined as T;

    const contentType = response.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase();
    const isJson = contentType === 'application/json' || contentType?.endsWith('+json');
    let data: unknown;
    if (isJson && text) {
      try { data = JSON.parse(text); }
      catch { if (response.ok) throw new ResponseError(response.status); }
    }
    if (!response.ok) {
      if (response.status === 401 && requestOptions.token) options.onUnauthorized?.(requestOptions.token);
      throw httpError(response.status, data);
    }
    if (!isJson || !text) throw new ResponseError(response.status);
    // TypeScript describes the backend contract, not runtime schema validation.
    return data as T;
  }

  return { request };
}

export type ApiClient = ReturnType<typeof createApiClient>;
