import { StrictMode } from 'react';
import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ApiError, NetworkError, ResponseError } from '../api/client';
import type { ChatHistoryMessage, ChatResponse, Citation } from '../api/contracts';
import { useGuestChat } from './useGuestChat';

type Sender = NonNullable<Parameters<typeof useGuestChat>[0]>;

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((accept, fail) => { resolve = accept; reject = fail; });
  return { promise, resolve, reject };
}

const reply = (answer = 'Grounded answer.'): ChatResponse => ({ answer, citations: [], conversation_id: null });

describe('guest chat state', () => {
  it('sends a trimmed first question with empty history, no ID, and no authorization', async () => {
    const send = vi.fn<Sender>().mockResolvedValue(reply());
    const { result } = renderHook(() => useGuestChat(send));
    await act(async () => { result.current.send('  Tyres?  '); });
    expect(send.mock.calls[0][0]).toEqual({ message: 'Tyres?', history: [] });
    expect(send.mock.calls[0][1]).toEqual({ signal: expect.any(AbortSignal) });
    expect(result.current.messages.map(({ role, content }) => ({ role, content }))).toEqual([
      { role: 'user', content: 'Tyres?' }, { role: 'assistant', content: 'Grounded answer.' },
    ]);
    expect(result.current.isPending).toBe(false);
    expect(result.current.draft).toBe('');
  });

  it('keeps all visible messages but sends only the last ten previous messages', async () => {
    const send = vi.fn<Sender>();
    const { result } = renderHook(() => useGuestChat(send));
    const history: ChatHistoryMessage[] = [];
    for (let index = 1; index <= 7; index++) {
      send.mockResolvedValueOnce(reply(`Answer ${index}`));
      await act(async () => { result.current.send(`Question ${index}`); });
      history.push({ role: 'user', content: `Question ${index}` }, { role: 'assistant', content: `Answer ${index}` });
    }
    expect(send.mock.calls[6][0]).toEqual({ message: 'Question 7', history: history.slice(2, 12) });
    expect(result.current.messages).toHaveLength(14);
    expect(result.current.messages[0].content).toBe('Question 1');
    expect(new Set(result.current.messages.map((message) => message.id)).size).toBe(14);
  });

  it('limits history content to the backend bound without truncating the displayed answer', async () => {
    const answer = 'a'.repeat(8100);
    const send = vi.fn<Sender>().mockResolvedValueOnce(reply(answer)).mockResolvedValueOnce(reply());
    const { result } = renderHook(() => useGuestChat(send));
    await act(async () => { result.current.send('First'); });
    await act(async () => { result.current.send('Follow-up'); });
    expect(result.current.messages[1].content).toBe(answer);
    expect(send.mock.calls[1][0].history?.[1].content).toHaveLength(8000);
  });

  it('keeps source metadata attached to its own answer, not in outgoing history', async () => {
    const citation: Citation = {
      source_id: 'S1', chunk_id: 'document:B6.3.6:0', document_id: 'document',
      document_title: 'Sporting Regulations', section: 'B', source_kind: 'clause',
      article_identifier: 'B6', clause_identifier: 'B6.3.6', appendix_identifier: null,
      start_pdf_page: 58, end_pdf_page: 58, snippet: 'Original excerpt',
    };
    const send = vi.fn<Sender>().mockResolvedValueOnce({ ...reply('First [S1]'), citations: [citation] })
      .mockResolvedValueOnce(reply('Insufficient evidence.'));
    const { result } = renderHook(() => useGuestChat(send));
    await act(async () => { result.current.send('First'); });
    await act(async () => { result.current.send('Follow-up'); });
    expect(result.current.messages[1].citations).toEqual([citation]);
    expect(result.current.messages[3].citations).toEqual([]);
    expect(send.mock.calls[1][0].history).toEqual([
      { role: 'user', content: 'First' }, { role: 'assistant', content: 'First [S1]' },
    ]);
  });

  it('blocks duplicate submissions synchronously and prevents draft changes while pending', async () => {
    const pending = deferred<ChatResponse>();
    const send = vi.fn<Sender>().mockReturnValue(pending.promise);
    const { result } = renderHook(() => useGuestChat(send));
    act(() => {
      expect(result.current.send('First')).toBe(true);
      expect(result.current.send('Duplicate')).toBe(false);
      result.current.updateDraft('Do not replace the pending question');
    });
    expect(send).toHaveBeenCalledTimes(1);
    expect(result.current.isPending).toBe(true);
    expect(result.current.activeTurn).toEqual({ question: 'First', status: 'loading' });
    expect(result.current.draft).toBe('');
    await act(async () => { pending.resolve(reply()); });
    expect(result.current.messages).toHaveLength(2);
  });

  it('rejects blank or oversized questions before calling the API', () => {
    const send = vi.fn<Sender>();
    const { result } = renderHook(() => useGuestChat(send));
    act(() => {
      expect(result.current.send('  ')).toBe(false);
      expect(result.current.send('q'.repeat(4001))).toBe(false);
    });
    expect(send).not.toHaveBeenCalled();
    expect(result.current.activeTurn).toBeNull();
  });

  it.each([new NetworkError(), new ApiError(422, 'Please check the question.'), new ResponseError(200)])
    ('restores a failed question and supports an explicit retry without duplicating history: %s', async (error) => {
      const send = vi.fn<Sender>().mockRejectedValueOnce(error).mockResolvedValueOnce(reply());
      const { result } = renderHook(() => useGuestChat(send));
      await act(async () => { result.current.send('  Retry me  '); });
      expect(result.current.activeTurn).toEqual({ question: 'Retry me', status: 'error', error: error.message });
      expect(result.current.draft).toBe('Retry me');
      expect(result.current.messages).toEqual([]);
      expect(result.current.isPending).toBe(false);
      expect(send).toHaveBeenCalledTimes(1);
      await act(async () => { result.current.send(result.current.draft); });
      expect(send.mock.calls[1][0]).toEqual({ message: 'Retry me', history: [] });
      expect(result.current.activeTurn).toBeNull();
      expect(result.current.messages).toHaveLength(2);
    });

  it('preserves completed history through a failed follow-up and excludes that failed turn', async () => {
    const send = vi.fn<Sender>().mockResolvedValueOnce(reply('First answer'))
      .mockRejectedValueOnce(new NetworkError()).mockResolvedValueOnce(reply('Third answer'));
    const { result } = renderHook(() => useGuestChat(send));
    await act(async () => { result.current.send('First'); });
    await act(async () => { result.current.send('Failed'); });
    await act(async () => { result.current.send('Edited question'); });
    expect(send.mock.calls[2][0]).toEqual({ message: 'Edited question', history: [
      { role: 'user', content: 'First' }, { role: 'assistant', content: 'First answer' },
    ] });
    expect(result.current.messages.map((message) => message.content)).toEqual([
      'First', 'First answer', 'Edited question', 'Third answer',
    ]);
  });

  it.each([undefined, { answer: '' }, { ...reply(), conversation_id: 2 }, { ...reply(), citations: null }])
    ('rejects malformed or unexpectedly saved guest responses: %s', async (response) => {
      const send = vi.fn<Sender>().mockResolvedValue(response as ChatResponse);
      const { result } = renderHook(() => useGuestChat(send));
      await act(async () => { result.current.send('Question'); });
      expect(result.current.messages).toEqual([]);
      expect(result.current.activeTurn).toMatchObject({ status: 'error', error: new ResponseError(200).message });
      expect(result.current.draft).toBe('Question');
    });

  it('does not expose unexpected exception details to the UI', async () => {
    const send = vi.fn<Sender>().mockRejectedValue(new Error('Internal sensitive data'));
    const { result } = renderHook(() => useGuestChat(send));
    await act(async () => { result.current.send('Question'); });
    expect(result.current.activeTurn).toMatchObject({ error: 'Unable to get an answer. Please try again.' });
  });

  it.each(['success', 'failure'] as const)('new chat cancels a request and ignores its stale %s', async (outcome) => {
    const old = deferred<ChatResponse>();
    const current = deferred<ChatResponse>();
    const send = vi.fn<Sender>().mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise);
    const { result } = renderHook(() => useGuestChat(send));
    act(() => { result.current.send('Old question'); });
    const signal = send.mock.calls[0][1].signal!;
    act(() => { result.current.newChat(); result.current.send('New question'); });
    expect(signal.aborted).toBe(true);
    expect(send.mock.calls[1][0]).toEqual({ message: 'New question', history: [] });
    await act(async () => {
      if (outcome === 'success') old.resolve(reply('Stale answer'));
      else old.reject(new NetworkError());
    });
    expect(result.current.activeTurn).toEqual({ question: 'New question', status: 'loading' });
    expect(result.current.messages).toEqual([]);
    act(() => { expect(result.current.send('Still locked')).toBe(false); });
    await act(async () => { current.resolve(reply('New answer')); });
    expect(result.current.messages.map((message) => message.content)).toEqual(['New question', 'New answer']);
  });

  it('new chat clears completed messages, draft, errors, and outgoing history', async () => {
    const send = vi.fn<Sender>().mockResolvedValueOnce(reply()).mockRejectedValueOnce(new NetworkError()).mockResolvedValueOnce(reply());
    const { result } = renderHook(() => useGuestChat(send));
    await act(async () => { result.current.send('First'); });
    await act(async () => { result.current.send('Failed'); });
    act(() => { result.current.newChat(); });
    expect(result.current.messages).toEqual([]);
    expect(result.current.draft).toBe('');
    expect(result.current.activeTurn).toBeNull();
    await act(async () => { result.current.send('Fresh'); });
    expect(send.mock.calls[2][0]).toEqual({ message: 'Fresh', history: [] });
  });

  it('aborts on unmount and a remount starts empty without accessing browser storage', async () => {
    const get = vi.spyOn(Storage.prototype, 'getItem');
    const set = vi.spyOn(Storage.prototype, 'setItem');
    try {
      const pending = deferred<ChatResponse>();
      const send = vi.fn<Sender>().mockResolvedValueOnce(reply()).mockReturnValueOnce(pending.promise);
      const first = renderHook(() => useGuestChat(send));
      await act(async () => { first.result.current.send('Completed'); });
      act(() => { first.result.current.send('Pending'); });
      const signal = send.mock.calls[1][1].signal!;
      first.unmount();
      expect(signal.aborted).toBe(true);
      await act(async () => { pending.resolve(reply('Late')); });
      const second = renderHook(() => useGuestChat(send));
      expect(second.result.current.messages).toEqual([]);
      expect(second.result.current.draft).toBe('');
      expect(get).not.toHaveBeenCalled();
      expect(set).not.toHaveBeenCalled();
    } finally { get.mockRestore(); set.mockRestore(); }
  });

  it('does not duplicate a user-triggered send under React StrictMode', async () => {
    const send = vi.fn<Sender>().mockResolvedValue(reply());
    const { result } = renderHook(() => useGuestChat(send), { wrapper: StrictMode });
    await act(async () => { result.current.send('Question'); });
    expect(send).toHaveBeenCalledTimes(1);
    expect(result.current.messages).toHaveLength(2);
  });
});
