import { useEffect, useRef, useState } from 'react';
import { ApiError, NetworkError, ResponseError } from '../api/client';
import type { ChatHistoryMessage, ChatRequest, ChatResponse, Citation, MessageRole } from '../api/contracts';
import type { RequestOptions } from '../api/client';
import { api } from '../api/endpoints';

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

function validateResponse(value: unknown): asserts value is ChatResponse {
  if (typeof value !== 'object' || value === null || !('answer' in value)
      || typeof value.answer !== 'string' || !value.answer.trim()
      || !('citations' in value) || !Array.isArray(value.citations)
      || !('conversation_id' in value) || value.conversation_id !== null) {
    throw new ResponseError(200);
  }
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError || error instanceof NetworkError || error instanceof ResponseError) {
    return error.message;
  }
  return 'Unable to get an answer. Please try again.';
}

// Guest state is deliberately not persisted to storage, cookies, or the URL.
export function useGuestChat(sendMessage: SendMessage = api.chat.send) {
  const [draft, setDraft] = useState('');
  const [messages, setMessages] = useState<GuestMessage[]>([]);
  const [activeTurn, setActiveTurn] = useState<ActiveTurn | null>(null);
  const messagesRef = useRef<GuestMessage[]>([]);
  const requestRef = useRef<AbortController | null>(null);
  const nextId = useRef(1);

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
    if (requestRef.current || !message || message.length > 4000) return false;
    const request = new AbortController();
    requestRef.current = request;
    const history = guestHistory(messagesRef.current);
    setDraft('');
    setActiveTurn({ question: message, status: 'loading' });

    async function run() {
      try {
        const response = await sendMessage({ message, history }, { signal: request.signal });
        // Some clients/mocks can finish after abort. Identity protects the new chat.
        if (requestRef.current !== request) return;
        validateResponse(response);
        const completed: GuestMessage[] = [
          ...messagesRef.current,
          { id: nextId.current++, role: 'user', content: message, citations: [] },
          { id: nextId.current++, role: 'assistant', content: response.answer, citations: response.citations },
        ];
        messagesRef.current = completed;
        setMessages(completed);
        setActiveTurn(null);
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
    setMessages([]);
    setActiveTurn(null);
    setDraft('');
  }

  return { draft, messages, activeTurn, isPending: activeTurn?.status === 'loading', updateDraft, send, newChat };
}
