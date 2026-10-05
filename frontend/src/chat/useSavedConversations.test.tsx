import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, NetworkError } from '../api/client';
import type { ConversationResponse } from '../api/contracts';
import { api } from '../api/endpoints';
import { conversation } from '../test/conversations';
import { useSavedConversations } from './useSavedConversations';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((accept) => { resolve = accept; });
  return { promise, resolve };
}
beforeEach(() => {
  vi.spyOn(api.conversations, 'list').mockResolvedValue([conversation(1), conversation(2)]);
  vi.spyOn(api.conversations, 'rename').mockResolvedValue(conversation(1, 'Updated title'));
  vi.spyOn(api.conversations, 'delete').mockResolvedValue(undefined);
});
afterEach(() => vi.restoreAllMocks());

describe('saved conversation list and mutations', () => {
  it('does not request saved data for guests', () => {
    const { result } = renderHook(() => useSavedConversations(null));
    expect(result.current.items).toEqual([]);
    expect(api.conversations.list).not.toHaveBeenCalled();
  });
  it('loads the current account list with a token and sorts by update time then ID', async () => {
    const { result } = renderHook(() => useSavedConversations('token'));
    await waitFor(() => expect(result.current.items).toHaveLength(2));
    expect(result.current.items.map((item) => item.id)).toEqual([2, 1]);
    expect(api.conversations.list).toHaveBeenCalledWith({ token: 'token', signal: expect.any(AbortSignal) });
  });
  it('supports retry after a list error', async () => {
    vi.mocked(api.conversations.list).mockRejectedValueOnce(new NetworkError());
    const { result } = renderHook(() => useSavedConversations('token'));
    await waitFor(() => expect(result.current.error).toContain('connection'));
    await act(async () => { await result.current.reload(); });
    expect(result.current.items).toHaveLength(2);
    expect(result.current.error).toBe('');
  });
  it('ignores an older list response after refresh', async () => {
    const first = deferred<ConversationResponse[]>();
    vi.mocked(api.conversations.list).mockReturnValueOnce(first.promise).mockResolvedValueOnce([conversation(3)]);
    const { result } = renderHook(() => useSavedConversations('token'));
    await act(async () => { await result.current.reload(); });
    await act(async () => { first.resolve([conversation(1)]); });
    expect(result.current.items.map((item) => item.id)).toEqual([3]);
    expect(vi.mocked(api.conversations.list).mock.calls[0][0].signal?.aborted).toBe(true);
  });
  it('renames using trimmed text and updates only the target row', async () => {
    const { result } = renderHook(() => useSavedConversations('token'));
    await waitFor(() => expect(result.current.items).toHaveLength(2));
    await act(async () => { expect(await result.current.rename(conversation(), '  Updated title  ')).toBe(true); });
    expect(api.conversations.rename).toHaveBeenCalledWith(1, { title: 'Updated title' }, { token: 'token', signal: expect.any(AbortSignal) });
    expect(result.current.items.find((item) => item.id === 1)?.title).toBe('Updated title');
    expect(result.current.items.find((item) => item.id === 2)?.title).toBe('Tyre requirements');
  });
  it.each([' ', 'a'.repeat(161)])('rejects invalid rename text before requesting', async (title) => {
    const { result } = renderHook(() => useSavedConversations('token'));
    await act(async () => { await expect(result.current.rename(conversation(), title)).rejects.toThrow('title'); });
    expect(api.conversations.rename).not.toHaveBeenCalled();
  });
  it('deletes the selected ID using the account token and accepts empty 204', async () => {
    const { result } = renderHook(() => useSavedConversations('token'));
    await waitFor(() => expect(result.current.items).toHaveLength(2));
    await act(async () => { expect(await result.current.delete(conversation(2))).toBe(true); });
    expect(api.conversations.delete).toHaveBeenCalledWith(2, { token: 'token', signal: expect.any(AbortSignal) });
    expect(result.current.items.map((item) => item.id)).toEqual([1]);
  });
  it('handles already-deleted conversations without recreating them', async () => {
    vi.mocked(api.conversations.delete).mockRejectedValue(new ApiError(404, 'Not found'));
    const { result } = renderHook(() => useSavedConversations('token'));
    await waitFor(() => expect(result.current.items).toHaveLength(2));
    await act(async () => { expect(await result.current.delete(conversation())).toBe(true); });
    expect(result.current.items.map((item) => item.id)).toEqual([2]);
  });
  it('does not remove data on a failed delete or accept a mismatched rename response', async () => {
    vi.mocked(api.conversations.delete).mockRejectedValue(new NetworkError());
    vi.mocked(api.conversations.rename).mockResolvedValue(conversation(99));
    const { result } = renderHook(() => useSavedConversations('token'));
    await waitFor(() => expect(result.current.items).toHaveLength(2));
    await act(async () => { await expect(result.current.delete(conversation())).rejects.toBeInstanceOf(NetworkError); });
    await act(async () => { await expect(result.current.rename(conversation(), 'New title')).rejects.toMatchObject({ name: 'ResponseError' }); });
    expect(result.current.items.map((item) => item.id)).toEqual([2, 1]);
  });
  it('blocks duplicate mutations and queues refresh until mutation finishes', async () => {
    const pending = deferred<ConversationResponse>();
    vi.mocked(api.conversations.rename).mockReturnValue(pending.promise);
    const { result } = renderHook(() => useSavedConversations('token'));
    await waitFor(() => expect(result.current.items).toHaveLength(2));
    let task!: Promise<boolean>;
    await act(async () => {
      task = result.current.rename(conversation(), 'Updated title');
      expect(await result.current.delete(conversation())).toBe(false);
      await result.current.reload();
    });
    expect(api.conversations.list).toHaveBeenCalledTimes(1);
    vi.mocked(api.conversations.list).mockResolvedValue([conversation(1, 'Updated title')]);
    await act(async () => { pending.resolve(conversation(1, 'Updated title')); await task; });
    expect(api.conversations.rename).toHaveBeenCalledOnce();
    expect(api.conversations.list).toHaveBeenCalledTimes(2);
    expect(result.current.items[0].title).toBe('Updated title');
  });
  it('cancels list/mutation requests on logout/unmount and ignores late success', async () => {
    const pending = deferred<ConversationResponse>();
    vi.mocked(api.conversations.rename).mockReturnValue(pending.promise);
    const { result, unmount } = renderHook(() => useSavedConversations('token'));
    await waitFor(() => expect(result.current.items).toHaveLength(2));
    let task!: Promise<boolean>;
    await act(async () => { task = result.current.rename(conversation(), 'Changed'); });
    unmount();
    expect(vi.mocked(api.conversations.rename).mock.calls[0][2].signal?.aborted).toBe(true);
    await act(async () => { pending.resolve(conversation(1, 'Changed')); expect(await task).toBe(false); });
  });
});
