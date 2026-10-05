import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';
import { ApiError, NetworkError } from './api/client';
import { api } from './api/endpoints';
import { SESSION_STORAGE_KEY } from './auth/sessionEvents';
import { conversation, conversationDetail } from './test/conversations';

beforeEach(() => {
  sessionStorage.setItem(SESSION_STORAGE_KEY, 'token');
  vi.spyOn(api.auth, 'me').mockResolvedValue({ id: 1, username: 'assetk', created_at: '2026-10-05T12:00:00Z' });
  vi.spyOn(api.conversations, 'list').mockResolvedValue([conversation(1, 'Tyre rules'), conversation(2, 'Cost cap')]);
  vi.spyOn(api.conversations, 'get').mockImplementation(async (id) => conversationDetail(id, id === 1 ? 'Tyre rules' : 'Cost cap'));
  vi.spyOn(api.conversations, 'rename').mockResolvedValue(conversation(1, 'Renamed chat'));
  vi.spyOn(api.conversations, 'delete').mockResolvedValue(undefined);
  vi.spyOn(api.chat, 'send').mockResolvedValue({ answer: 'New saved answer', citations: [], conversation_id: 3 });
});
afterEach(() => { sessionStorage.removeItem(SESSION_STORAGE_KEY); vi.restoreAllMocks(); });
async function start() {
  const user = userEvent.setup();
  render(<App />);
  await screen.findByRole('button', { name: 'Open conversation: Tyre rules' });
  return user;
}

describe('saved conversation interface', () => {
  it('reopens messages/citations and updates the heading when renamed', async () => {
    const user = await start();
    await user.click(screen.getByRole('button', { name: 'Open conversation: Tyre rules' }));
    expect(await screen.findByRole('heading', { name: 'Tyre rules' })).toBeInTheDocument();
    expect(screen.getByRole('log')).toHaveTextContent('Saved answer for Tyre rules.');
    await user.click(within(screen.getByRole('group', { name: 'Sources' })).getByRole('button'));
    expect(screen.getByRole('dialog', { name: 'Source S1' })).toHaveTextContent('Sporting Regulations');
    await user.click(screen.getByRole('button', { name: 'Close source' }));
    const trigger = screen.getByRole('button', { name: 'Rename conversation: Tyre rules' });
    await user.click(trigger);
    await user.clear(screen.getByLabelText('Conversation title'));
    await user.type(screen.getByLabelText('Conversation title'), ' Renamed chat ');
    await user.click(screen.getByRole('button', { name: 'Save title' }));
    expect(await screen.findByRole('heading', { name: 'Renamed chat' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Rename conversation: Renamed chat' })).toHaveFocus();
    expect(api.conversations.rename).toHaveBeenCalledWith(1, { title: 'Renamed chat' }, { token: 'token', signal: expect.any(AbortSignal) });
  });

  it('delete cancellation makes no mutation; confirming deletion clears the selected chat', async () => {
    const user = await start();
    await user.click(screen.getByRole('button', { name: 'Open conversation: Tyre rules' }));
    await screen.findByRole('heading', { name: 'Tyre rules' });
    const trigger = screen.getByRole('button', { name: 'Delete conversation: Tyre rules' });
    await user.click(trigger);
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(api.conversations.delete).not.toHaveBeenCalled();
    expect(trigger).toHaveFocus();
    await user.click(trigger);
    await user.click(screen.getByRole('button', { name: 'Delete conversation' }));
    await screen.findByRole('heading', { name: 'Know the rules.' });
    expect(screen.queryByRole('button', { name: 'Open conversation: Tyre rules' })).not.toBeInTheDocument();
    expect(screen.queryByRole('log')).not.toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Your question' })).toHaveFocus();
    expect(api.conversations.delete).toHaveBeenCalledExactlyOnceWith(1, { token: 'token', signal: expect.any(AbortSignal) });
  });

  it('failed deletion stays in its dialog and preserves the saved conversation', async () => {
    vi.mocked(api.conversations.delete).mockRejectedValue(new NetworkError());
    const user = await start();
    await user.click(screen.getByRole('button', { name: 'Delete conversation: Tyre rules' }));
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Delete conversation' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('connection');
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Open conversation: Tyre rules' })).toBeInTheDocument();
  });

  it('invalid rename stays local and Cancel preserves the title', async () => {
    const user = await start();
    await user.click(screen.getByRole('button', { name: 'Rename conversation: Tyre rules' }));
    await user.clear(screen.getByLabelText('Conversation title'));
    await user.click(screen.getByRole('button', { name: 'Save title' }));
    expect(screen.getByLabelText('Conversation title')).toHaveAttribute('aria-invalid', 'true');
    expect(api.conversations.rename).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.getByRole('button', { name: 'Open conversation: Tyre rules' })).toBeInTheDocument();
  });

  it('a new authenticated turn appears in the refreshed list without importing guest history', async () => {
    const user = await start();
    vi.mocked(api.conversations.list).mockResolvedValue([conversation(3, 'New question')]);
    await user.type(screen.getByRole('textbox', { name: 'Your question' }), 'New question{Enter}');
    expect(await screen.findByRole('button', { name: 'Open conversation: New question' })).toHaveAttribute('aria-current', 'page');
    expect(api.chat.send).toHaveBeenCalledWith({ message: 'New question' }, { token: 'token', signal: expect.any(AbortSignal) });
  });

  it('inaccessible conversations replace the transcript with an error and allow a new chat', async () => {
    const user = await start();
    await user.click(screen.getByRole('button', { name: 'Open conversation: Tyre rules' }));
    await screen.findByRole('heading', { name: 'Tyre rules' });
    vi.mocked(api.conversations.get).mockRejectedValue(new ApiError(404, 'Not found'));
    await user.click(screen.getByRole('button', { name: 'Open conversation: Cost cap' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('accessible');
    expect(screen.queryByRole('log')).not.toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: 'Your question' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Start a new chat' }));
    expect(screen.getByRole('textbox', { name: 'Your question' })).toHaveValue('');
  });

  it('mobile navigation opens history, manages a row, and returns to the updated list', async () => {
    const user = await start();
    await user.click(screen.getByRole('button', { name: 'Navigation menu' }));
    await user.click(screen.getByRole('button', { name: 'Saved chats' }));
    const history = screen.getByRole('dialog', { name: 'Saved chats' });
    await user.click(within(history).getByRole('button', { name: 'Rename conversation: Tyre rules' }));
    expect(screen.queryByRole('dialog', { name: 'Saved chats' })).not.toBeInTheDocument();
    await user.clear(screen.getByLabelText('Conversation title'));
    await user.type(screen.getByLabelText('Conversation title'), 'Renamed chat');
    await user.click(screen.getByRole('button', { name: 'Save title' }));
    const updated = await screen.findByRole('dialog', { name: 'Saved chats' });
    expect(within(updated).getByRole('button', { name: 'Open conversation: Renamed chat' })).toBeInTheDocument();
    await user.click(within(updated).getByRole('button', { name: 'Close saved chats' }));
    expect(screen.getByRole('button', { name: 'Navigation menu' })).toHaveFocus();
    expect(document.documentElement.style.overflow).not.toBe('hidden');
  });

  it('logout removes saved rows and ignores an in-flight list result', async () => {
    const user = await start();
    let resolve!: (value: ReturnType<typeof conversation>[]) => void;
    vi.mocked(api.conversations.list).mockReturnValue(new Promise((accept) => { resolve = accept; }));
    await user.click(screen.getByRole('button', { name: 'Refresh saved chats' }));
    await user.click(screen.getByRole('button', { name: 'Account: assetk' }));
    await user.click(screen.getByRole('button', { name: 'Sign out' }));
    await act(async () => { resolve([conversation(8, 'Late private row')]); });
    expect(screen.queryByRole('navigation', { name: 'Saved conversations' })).not.toBeInTheDocument();
    expect(screen.queryByText('Late private row')).not.toBeInTheDocument();
  });
});
