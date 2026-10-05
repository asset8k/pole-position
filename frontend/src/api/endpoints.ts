import { createApiClient } from './client';
import { reportUnauthorized } from '../auth/sessionEvents';
import type { ApiClient, RequestOptions } from './client';
import type {
  ChatRequest, ChatResponse, ConversationDetailResponse, ConversationResponse,
  ConversationUpdateRequest, LoginRequest, RegisterRequest, TokenResponse, UserResponse,
} from './contracts';

export interface AuthenticatedRequestOptions extends RequestOptions {
  token: string;
}

function requireToken(options: AuthenticatedRequestOptions): AuthenticatedRequestOptions {
  if (!options.token.trim()) throw new TypeError('An access token is required.');
  return options;
}

function conversationPath(id: number): string {
  if (!Number.isSafeInteger(id) || id <= 0) {
    throw new TypeError('Conversation ID must be a positive integer.');
  }
  return `/conversations/${id}`;
}

export function createApi(client: ApiClient = createApiClient()) {
  return {
    chat: {
      send(body: ChatRequest, options: RequestOptions = {}) {
        return client.request<ChatResponse>('/chat', { ...options, method: 'POST', body });
      },
    },
    auth: {
      register(body: RegisterRequest, options: Pick<RequestOptions, 'signal'> = {}) {
        return client.request<UserResponse>('/auth/register', { ...options, method: 'POST', body });
      },
      login(body: LoginRequest, options: Pick<RequestOptions, 'signal'> = {}) {
        return client.request<TokenResponse>('/auth/login', { ...options, method: 'POST', body });
      },
      me(options: AuthenticatedRequestOptions) {
        return client.request<UserResponse>('/auth/me', requireToken(options));
      },
    },
    conversations: {
      list(options: AuthenticatedRequestOptions) {
        return client.request<ConversationResponse[]>('/conversations', requireToken(options));
      },
      get(id: number, options: AuthenticatedRequestOptions) {
        return client.request<ConversationDetailResponse>(conversationPath(id), requireToken(options));
      },
      rename(id: number, body: ConversationUpdateRequest, options: AuthenticatedRequestOptions) {
        return client.request<ConversationResponse>(conversationPath(id), {
          ...requireToken(options), method: 'PATCH', body,
        });
      },
      delete(id: number, options: AuthenticatedRequestOptions) {
        return client.request<void>(conversationPath(id), {
          ...requireToken(options), method: 'DELETE',
        });
      },
    },
  };
}

// Session storage is owned by useSession, never by the transport layer.
export const api = createApi(createApiClient({ onUnauthorized: reportUnauthorized }));
