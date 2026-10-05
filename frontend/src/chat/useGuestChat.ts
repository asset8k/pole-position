import { useEffect, useRef, useState } from 'react';
import { ApiError, NetworkError, ResponseError } from '../api/client';
import type { ChatHistoryMessage, ChatRequest, ChatResponse, Citation, MessageRole } from '../api/contracts';
import type { RequestOptions } from '../api/client';
import { api } from '../api/endpoints';
import { conversationError, validateConversationDetail } from './conversationValidation';

export interface GuestMessage {
  id: number;
  role: MessageRole;
  content: string;
  citations: Citation[];
}

export type ActiveTurn =
  | { question: string; status: 'loading' }
  | { question: string; status: 'error'; error: string };

type SendMessage = (body: ChatRequest, options: RequestOptions) => Promise<ChatResponse>;

function guestHistory(messages: GuestMessage[]): ChatHistoryMessage[] {
  // Only completed messages; never include the new question or a failed attempt.
  return messages.slice(-10).map(({ role, content }) => ({
    role, content: content.slice(0, 8000), // The backend's per-history-message limit.
  }));
}

function validateResponse(value: unknown, authenticated: boolean): asserts value is ChatResponse {
  if (typeof value !== 'object' || value === null || !('answer' in value)
      || typeof value.answer !== 'string' || !value.answer.trim()
      || !('citations' in value) || !Array.isArray(value.citations)
      || !('conversation_id' in value)
      || (authenticated ? !Number.isSafeInteger(value.conversation_id) || Number(value.conversation_id) <= 0
        : value.conversation_id !== null)) {
    throw new ResponseError(200);
  }
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError || error instanceof NetworkError || error instanceof ResponseError) {
    return error.message;
  }
  return 'Unable to get an answer. Please try again.';
}

// Transcripts are never persisted in the browser. Registered requests are saved
// by the existing backend; guests use only temporary client history.
export function useChat({ sendMessage = api.chat.send, token = null, onSaved, onMissing }: {
  sendMessage?: SendMessage; token?: string | null;
  onSaved?: (id: number) => void;
  onMissing?: (id: number) => void;
} = {}) {
  const [draft, setDraft] = useState('');
  const [messages, setMessages] = useState<GuestMessage[]>([]);
  const [activeTurn, setActiveTurn] = useState<ActiveTurn | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loadState, setLoadState] = useState<{ status: 'loading' } | { status: 'error'; error: string } | null>(null);
  const messagesRef = useRef<GuestMessage[]>([]);
  const requestRef = useRef<AbortController | null>(null);
  const nextId = useRef(1);
  const conversationId = useRef<number | null>(null);
  const loadBlocked = useRef(false);
  const callbacks = useRef({ onSaved, onMissing });
  callbacks.current = { onSaved, onMissing };

  useEffect(() => () => {
    const request = requestRef.current;
    requestRef.current = null;
    request?.abort();
  }, []);

  function updateDraft(value: string) {
    if (!requestRef.current) setDraft(value);
  }

  function send(question: string): boolean {
    const message = question.trim();
    // A synchronous lock also blocks double clicks before React's next render.
    if (requestRef.current || loadBlocked.current || !message || message.length > 4000) return false;
    const request = new AbortController();
    requestRef.current = request;
    const history = guestHistory(messagesRef.current);
    const requestedId = conversationId.current;
    setDraft('');
    setActiveTurn({ question: message, status: 'loading' });

    async function run() {
      try {
        const body: ChatRequest = token
          ? { message, ...(requestedId ? { conversation_id: requestedId } : {}) }
          : { message, history };
        const response = await sendMessage(body, { signal: request.signal, ...(token ? { token } : {}) });
        // Some clients/mocks can finish after abort. Identity protects the new chat.
        if (requestRef.current !== request) return;
        validateResponse(response, token !== null);
        if (requestedId !== null && response.conversation_id !== requestedId) throw new ResponseError(200);
        if (token) {
          conversationId.current = response.conversation_id;
          setSelectedId(response.conversation_id);
        }
        const completed: GuestMessage[] = [
          ...messagesRef.current,
          { id: nextId.current++, role: 'user', content: message, citations: [] },
          { id: nextId.current++, role: 'assistant', content: response.answer, citations: response.citations },
        ];
        messagesRef.current = completed;
        setMessages(completed);
        setActiveTurn(null);
        if (token && response.conversation_id) callbacks.current.onSaved?.(response.conversation_id);
      } catch (error) {
        if (requestRef.current !== request) return;
        setActiveTurn({ question: message, status: 'error', error: errorMessage(error) });
        setDraft(message); // Explicit resend via the composer; no automatic retries.
      } finally {
        if (requestRef.current === request) requestRef.current = null;
      }
    }
    void run();
    return true;
  }

  function newChat() {
    const request = requestRef.current;
    requestRef.current = null;
    request?.abort();
    messagesRef.current = [];
    conversationId.current = null;
    loadBlocked.current = false;
    setSelectedId(null);
    setLoadState(null);
    setMessages([]);
    setActiveTurn(null);
    setDraft('');
  }

  async function openConversation(id: number): Promise<boolean> {
    if (!token || !Number.isSafeInteger(id) || id <= 0) return false;
    newChat();
    loadBlocked.current = true;
    setSelectedId(id);
    setLoadState({ status: 'loading' });
    const request = new AbortController();
    requestRef.current = request;
    try {
      const detail = await api.conversations.get(id, { token, signal: request.signal });
      if (requestRef.current !== request) return false;
      validateConversationDetail(detail, id);
      const loaded = detail.messages.map(({ id: messageId, role, content, citations }) => ({ id: messageId, role, content, citations }));
      messagesRef.current = loaded;
      nextId.current = loaded.reduce((max, message) => Math.max(max, message.id), 0) + 1;
      conversationId.current = id;
      loadBlocked.current = false;
      setMessages(loaded);
      setLoadState(null);
      return true;
    } catch (cause) {
      if (requestRef.current !== request) return false;
      if (cause instanceof ApiError && (cause.status === 403 || cause.status === 404)) callbacks.current.onMissing?.(id);
      setLoadState({ status: 'error', error: conversationError(cause) });
      return false;
    } finally {
      if (requestRef.current === request) requestRef.current = null;
    }
  }

  return { draft, messages, activeTurn, selectedId, loadState, openConversation,
    isPending: activeTurn?.status === 'loading', updateDraft, send, newChat };
}

// Kept as a guest-only convenience for isolated guest tests and consumers.
export function useGuestChat(sendMessage: SendMessage = api.chat.send) {
  return useChat({ sendMessage });
}
