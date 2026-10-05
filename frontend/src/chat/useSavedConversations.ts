import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '../api/client';
import type { ConversationResponse } from '../api/contracts';
import { api } from '../api/endpoints';
import { conversationError, validateConversation, validateConversationList } from './conversationValidation';

function ordered(items: ConversationResponse[]) {
  return [...items].sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at) || b.id - a.id);
}

export function useSavedConversations(token: string | null) {
  const [items, setItems] = useState<ConversationResponse[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [mutation, setMutation] = useState<{ id: number; kind: 'rename' | 'delete' } | null>(null);
  const listRequest = useRef<AbortController | null>(null);
  const mutationRequest = useRef<AbortController | null>(null);
  const refreshQueued = useRef(false);

  const cancelList = useCallback(() => {
    const previous = listRequest.current;
    listRequest.current = null;
    previous?.abort();
  }, []);

  const reload = useCallback(async () => {
    if (mutationRequest.current) { refreshQueued.current = true; return; }
    cancelList();
    if (!token) return;
    const request = new AbortController();
    listRequest.current = request;
    setLoading(true); setError('');
    try {
      const result = await api.conversations.list({ token, signal: request.signal });
      if (listRequest.current !== request) return;
      validateConversationList(result);
      setItems(ordered(result));
    } catch (cause) {
      if (listRequest.current === request) setError(conversationError(cause, 'load your conversations'));
    } finally {
      if (listRequest.current === request) { listRequest.current = null; setLoading(false); }
    }
  }, [cancelList, token]);

  useEffect(() => {
    void reload();
    return () => {
      cancelList();
      const previous = mutationRequest.current;
      mutationRequest.current = null;
      previous?.abort();
    };
  }, [reload, cancelList]);

  const remove = useCallback((id: number) => {
    cancelList(); setLoading(false);
    setItems((previous) => previous.filter((item) => item.id !== id));
  }, [cancelList]);

  async function mutate(kind: 'rename' | 'delete', item: ConversationResponse, title?: string): Promise<boolean> {
    if (!token || mutationRequest.current) return false;
    const trimmed = title?.trim();
    if (kind === 'rename' && (!trimmed || trimmed.length > 160)) throw new Error('Use a title between 1 and 160 characters.');
    cancelList(); setLoading(false);
    const request = new AbortController();
    mutationRequest.current = request;
    setMutation({ id: item.id, kind });
    try {
      if (kind === 'rename') {
        const result = await api.conversations.rename(item.id, { title: trimmed! }, { token, signal: request.signal });
        if (mutationRequest.current !== request) return false;
        validateConversation(result, item.id);
        setItems((previous) => ordered([...previous.filter((entry) => entry.id !== result.id), result]));
      } else {
        await api.conversations.delete(item.id, { token, signal: request.signal });
        if (mutationRequest.current !== request) return false;
        remove(item.id);
      }
      setError('');
      return true;
    } catch (cause) {
      if (mutationRequest.current !== request) return false;
      // A previously deleted conversation is already in the desired state.
      if (cause instanceof ApiError && cause.status === 404) {
        remove(item.id);
        if (kind === 'delete') return true;
      }
      throw cause;
    } finally {
      if (mutationRequest.current === request) {
        mutationRequest.current = null; setMutation(null);
        if (refreshQueued.current) { refreshQueued.current = false; void reload(); }
      }
    }
  }

  return { items, loading, error, mutation, reload, remove,
    rename: (item: ConversationResponse, title: string) => mutate('rename', item, title),
    delete: (item: ConversationResponse) => mutate('delete', item),
  };
}

export type SavedConversations = ReturnType<typeof useSavedConversations>;
