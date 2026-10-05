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

    let response: Response;
    let text: string;
    try {
      // Never retry mutations automatically; chat can create a saved conversation.
      response = await (options.fetch ?? globalThis.fetch)(`${baseUrl}${path}`, {
        method: requestOptions.method ?? 'GET',
        headers,
        body,
        signal: requestOptions.signal,
        credentials: 'omit',
      });
      if (response.status === 204) return undefined as T;
      text = await response.text();
    } catch (error) {
      // Let callers distinguish cancellation from a failed connection.
      if (isAbort(error) || requestOptions.signal?.aborted) throw error;
      throw new NetworkError();
    }

    const contentType = response.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase();
    const isJson = contentType === 'application/json' || contentType?.endsWith('+json');
    let data: unknown;
    if (isJson && text) {
      try { data = JSON.parse(text); }
      catch { if (response.ok) throw new ResponseError(response.status); }
    }
    if (!response.ok) throw httpError(response.status, data);
    if (!isJson || !text) throw new ResponseError(response.status);
    // TypeScript describes the backend contract, not runtime schema validation.
    return data as T;
  }

  return { request };
}

export type ApiClient = ReturnType<typeof createApiClient>;
