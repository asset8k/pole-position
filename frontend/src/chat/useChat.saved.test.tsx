import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../api/client';
import type { ChatResponse, ConversationDetailResponse } from '../api/contracts';
import { api } from '../api/endpoints';
import { conversationDetail } from '../test/conversations';
import { useChat } from './useGuestChat';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((accept) => { resolve = accept; });
  return { promise, resolve };
}
beforeEach(() => vi.spyOn(api.conversations, 'get').mockImplementation(async (id) => conversationDetail(id)));
afterEach(() => vi.restoreAllMocks());

describe('saved chat selection and sends', () => {
  it('loads all ordered messages and citations; follow-ups use ID/token and omit history', async () => {
    const send = vi.fn().mockResolvedValue({ answer: 'Follow-up answer', citations: [], conversation_id: 7 });
    const { result } = renderHook(() => useChat({ token: 'token', sendMessage: send }));
    await act(async () => { expect(await result.current.openConversation(7)).toBe(true); });
    expect(result.current.selectedId).toBe(7);
    expect(result.current.messages[1].citations).toEqual(conversationDetail(7).messages[1].citations);
    expect(result.current.messages[1].animateAnswer).toBeUndefined();
    await act(async () => { result.current.send('What about that?'); });
    expect(send).toHaveBeenCalledWith({ message: 'What about that?', conversation_id: 7 }, { token: 'token', signal: expect.any(AbortSignal) });
    expect(result.current.messages).toHaveLength(4);
    expect(result.current.messages[3].animateAnswer).toBe(true);
    expect(new Set(result.current.messages.map((message) => message.id)).size).toBe(4);
  });
  it('preserves older messages beyond the ten used for backend contextualization', async () => {
    const detail = conversationDetail(1);
    detail.messages = Array.from({ length: 100 }, (_, index) => ({ ...detail.messages[index % 2], id: index + 1, content: `Message ${index + 1}` }));
    vi.mocked(api.conversations.get).mockResolvedValue(detail);
    const { result } = renderHook(() => useChat({ token: 'token' }));
    await act(async () => { await result.current.openConversation(1); });
    expect(result.current.messages).toHaveLength(100);
    expect(result.current.messages[0].content).toBe('Message 1');
  });
  it('ignores out-of-order detail responses and blocks sending during loading', async () => {
    const slow = deferred<ConversationDetailResponse>();
    vi.mocked(api.conversations.get).mockReturnValueOnce(slow.promise).mockResolvedValueOnce(conversationDetail(2));
    const send = vi.fn();
    const { result } = renderHook(() => useChat({ token: 'token', sendMessage: send }));
    let opening!: Promise<boolean>;
    await act(async () => { opening = result.current.openConversation(1); expect(result.current.send('Too soon')).toBe(false); });
    await act(async () => { await result.current.openConversation(2); });
    await act(async () => { slow.resolve(conversationDetail(1)); expect(await opening).toBe(false); });
    expect(result.current.selectedId).toBe(2);
    expect(result.current.messages[0].id).toBe(201);
    expect(send).not.toHaveBeenCalled();
    expect(vi.mocked(api.conversations.get).mock.calls[0][1].signal?.aborted).toBe(true);
  });
  it('starting a new chat cancels detail loading; its first send omits the prior ID', async () => {
    const slow = deferred<ConversationDetailResponse>();
    vi.mocked(api.conversations.get).mockReturnValue(slow.promise);
    const send = vi.fn().mockResolvedValue({ answer: 'New answer', citations: [], conversation_id: 8 });
    const onSaved = vi.fn();
    const { result } = renderHook(() => useChat({ token: 'token', sendMessage: send, onSaved }));
    let opening!: Promise<boolean>;
    await act(async () => { opening = result.current.openConversation(1); });
    act(() => result.current.newChat());
    await act(async () => { slow.resolve(conversationDetail(1)); await opening; result.current.send('New question'); });
    expect(send).toHaveBeenCalledWith({ message: 'New question' }, { token: 'token', signal: expect.any(AbortSignal) });
    expect(onSaved).toHaveBeenCalledExactlyOnceWith(8);
    expect(result.current.selectedId).toBe(8);
  });
  it('switching chats ignores a late answer from the previous conversation', async () => {
    const slow = deferred<ChatResponse>();
    const send = vi.fn().mockReturnValue(slow.promise);
    const { result } = renderHook(() => useChat({ token: 'token', sendMessage: send }));
    await act(async () => { await result.current.openConversation(1); });
    act(() => { result.current.send('Pending in first'); });
    await act(async () => { await result.current.openConversation(2); });
    await act(async () => { slow.resolve({ answer: 'Late first answer', citations: [], conversation_id: 1 }); });
    expect(result.current.selectedId).toBe(2);
    expect(result.current.messages.some((message) => message.content === 'Late first answer')).toBe(false);
  });
  it.each([403, 404])('inaccessible HTTP %i details clear prior messages and cannot receive follow-ups', async (status) => {
    const onMissing = vi.fn();
    const send = vi.fn();
    const { result } = renderHook(() => useChat({ token: 'token', sendMessage: send, onMissing }));
    await act(async () => { await result.current.openConversation(1); });
    vi.mocked(api.conversations.get).mockRejectedValueOnce(new ApiError(status, 'Private detail'));
    await act(async () => { expect(await result.current.openConversation(2)).toBe(false); });
    expect(result.current.messages).toEqual([]);
    expect(result.current.loadState).toMatchObject({ status: 'error', error: expect.stringContaining('accessible') });
    expect(onMissing).toHaveBeenCalledWith(2);
    act(() => { expect(result.current.send('Unsafe follow-up')).toBe(false); });
    expect(send).not.toHaveBeenCalled();
  });
  it('rejects cross-conversation responses rather than changing IDs silently', async () => {
    const send = vi.fn().mockResolvedValue({ answer: 'Wrong conversation', citations: [], conversation_id: 99 });
    const { result } = renderHook(() => useChat({ token: 'token', sendMessage: send }));
    await act(async () => { await result.current.openConversation(1); result.current.send('Question'); });
    expect(result.current.selectedId).toBe(1);
    expect(result.current.activeTurn?.status).toBe('error');
    expect(result.current.messages).toHaveLength(2);
  });
  it('guests cannot open saved conversations', async () => {
    const { result } = renderHook(() => useChat());
    await act(async () => { expect(await result.current.openConversation(1)).toBe(false); });
    expect(api.conversations.get).not.toHaveBeenCalled();
  });
});
