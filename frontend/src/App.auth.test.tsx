import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';
import { ApiError } from './api/client';
import { api } from './api/endpoints';
import { SESSION_STORAGE_KEY, reportUnauthorized } from './auth/sessionEvents';
import { citation } from './test/citations';

const identity = { id: 1, username: 'assetk', created_at: '2026-10-05T12:00:00Z' };
beforeEach(() => {
  sessionStorage.removeItem(SESSION_STORAGE_KEY);
  vi.spyOn(api.auth, 'me').mockResolvedValue(identity);
  vi.spyOn(api.auth, 'login').mockResolvedValue({ access_token: 'test-token', token_type: 'bearer' });
  vi.spyOn(api.auth, 'register').mockResolvedValue(identity);
  vi.spyOn(api.conversations, 'list').mockResolvedValue([]);
  vi.spyOn(api.chat, 'send').mockResolvedValue({ answer: 'Private answer [S1]', citations: [citation()], conversation_id: 2 });
});
afterEach(() => { sessionStorage.removeItem(SESSION_STORAGE_KEY); vi.restoreAllMocks(); });

async function openLogin() {
  const user = userEvent.setup();
  await user.click(screen.getByRole('button', { name: 'Sign in' }));
  const dialog = screen.getByRole('dialog');
  return { user, dialog };
}
async function fillAndSignIn() {
  const { user, dialog } = await openLogin();
  await user.type(within(dialog).getByLabelText('Username'), 'assetk');
  await user.type(within(dialog).getByLabelText('Password'), 'securepassword123');
  await user.click(within(dialog).getByRole('button', { name: 'Sign in' }));
  await screen.findByRole('button', { name: 'Account: assetk' });
  return user;
}

describe('authentication UI', () => {
  it('checks credentials locally and makes no call for invalid values', async () => {
    render(<App />);
    const { user, dialog } = await openLogin();
    await user.type(within(dialog).getByLabelText('Username'), 'AssetK');
    await user.type(within(dialog).getByLabelText('Password'), 'short');
    await user.click(within(dialog).getByRole('button', { name: 'Sign in' }));
    expect(api.auth.login).not.toHaveBeenCalled();
    expect(within(dialog).getByLabelText('Username')).toHaveAttribute('aria-invalid', 'true');
    expect(within(dialog).getByLabelText('Password')).toHaveAttribute('aria-invalid', 'true');
  });

  it.each([[401, 'Incorrect username or password.'], [422, 'Check your username and password requirements.']])(
    'shows a safe login error for HTTP %i', async (status, message) => {
      vi.mocked(api.auth.login).mockRejectedValue(new ApiError(status, 'Unsafe secret detail'));
      render(<App />);
      const { user, dialog } = await openLogin();
      await user.type(within(dialog).getByLabelText('Username'), 'assetk');
      await user.type(within(dialog).getByLabelText('Password'), 'securepassword123');
      await user.click(within(dialog).getByRole('button', { name: 'Sign in' }));
      expect(await screen.findByRole('alert')).toHaveTextContent(message);
      expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
    },
  );

  it('reports duplicate registration without attempting login', async () => {
    vi.mocked(api.auth.register).mockRejectedValue(new ApiError(409, 'Username exists'));
    render(<App />);
    const { user, dialog } = await openLogin();
    await user.click(within(dialog).getByRole('button', { name: 'Create an account' }));
    await user.type(within(dialog).getByLabelText('Username'), 'assetk');
    await user.type(within(dialog).getByLabelText('Password'), 'securepassword123');
    await user.click(within(dialog).getByRole('button', { name: 'Create account' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('already taken');
    expect(api.auth.login).not.toHaveBeenCalled();
  });

  it('clears guest state on login and sends authenticated follow-ups without client history', async () => {
    render(<App />);
    vi.mocked(api.chat.send).mockResolvedValueOnce({ answer: 'Guest answer', citations: [], conversation_id: null });
    const user = userEvent.setup();
    await user.type(screen.getByRole('textbox', { name: 'Your question' }), 'Guest question{Enter}');
    await screen.findByText('Guest answer');
    await fillAndSignIn();
    expect(screen.queryByText('Guest answer')).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('save to your account');
    await user.type(screen.getByRole('textbox', { name: 'Your question' }), 'Private question{Enter}');
    await screen.findByText('Private question');
    await screen.findByRole('group', { name: 'Sources' });
    expect(api.chat.send).toHaveBeenLastCalledWith({ message: 'Private question' }, { token: 'test-token', signal: expect.any(AbortSignal) });
    await user.type(screen.getByRole('textbox', { name: 'Your question' }), 'Follow-up{Enter}');
    await screen.findByText('Follow-up');
    expect(api.chat.send).toHaveBeenLastCalledWith({ message: 'Follow-up', conversation_id: 2 }, { token: 'test-token', signal: expect.any(AbortSignal) });
  });

  it('logout clears transcript, draft, source drawer, account UI, and stored token', async () => {
    render(<App />);
    const user = await fillAndSignIn();
    await user.type(screen.getByRole('textbox', { name: 'Your question' }), 'Private question{Enter}');
    await screen.findByRole('group', { name: 'Sources' });
    await user.type(screen.getByRole('textbox', { name: 'Your question' }), 'Private draft');
    await user.click(within(screen.getByRole('group', { name: 'Sources' })).getByRole('button'));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    act(() => reportUnauthorized('test-token'));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.queryByText('Private question')).not.toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Your question' })).toHaveValue('');
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument();
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
    expect(document.documentElement.style.overflow).not.toBe('hidden');
  });

  it('account menu supports Escape and sign out', async () => {
    render(<App />);
    const user = await fillAndSignIn();
    const trigger = screen.getByRole('button', { name: 'Account: assetk' });
    await user.click(trigger);
    expect(screen.getByRole('button', { name: 'Sign out' })).toHaveFocus();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('region', { name: 'Your account' })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    await user.click(trigger);
    await user.click(screen.getByRole('button', { name: 'Sign out' }));
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument();
  });

  it('signing out during a private chat aborts it and ignores its late answer', async () => {
    let resolve!: (value: { answer: string; citations: never[]; conversation_id: number }) => void;
    vi.mocked(api.chat.send).mockReturnValue(new Promise((accept) => { resolve = accept; }));
    render(<App />);
    const user = await fillAndSignIn();
    await user.type(screen.getByRole('textbox', { name: 'Your question' }), 'Pending private question{Enter}');
    await user.click(screen.getByRole('button', { name: 'Account: assetk' }));
    await user.click(screen.getByRole('button', { name: 'Sign out' }));
    expect(vi.mocked(api.chat.send).mock.calls[0][1]?.signal?.aborted).toBe(true);
    await act(async () => { resolve({ answer: 'Late private answer', citations: [], conversation_id: 2 }); });
    expect(screen.queryByText('Late private answer')).not.toBeInTheDocument();
    expect(screen.queryByText('Pending private question')).not.toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Your question' })).toHaveValue('');
  });

  it('closing pending sign-in aborts it and ignores a late success', async () => {
    let resolve!: (value: { access_token: string; token_type: string }) => void;
    vi.mocked(api.auth.login).mockReturnValue(new Promise((accept) => { resolve = accept; }));
    render(<App />);
    const { user, dialog } = await openLogin();
    await user.type(within(dialog).getByLabelText('Username'), 'assetk');
    await user.type(within(dialog).getByLabelText('Password'), 'securepassword123');
    fireEvent.submit(within(dialog).getByRole('button', { name: 'Sign in' }).closest('form')!);
    fireEvent.submit(within(dialog).getByRole('button', { name: 'Please wait…' }).closest('form')!);
    expect(api.auth.login).toHaveBeenCalledOnce();
    await user.click(screen.getByRole('button', { name: 'Close sign in' }));
    expect(vi.mocked(api.auth.login).mock.calls[0][1]?.signal?.aborted).toBe(true);
    await act(async () => { resolve({ access_token: 'late-token', token_type: 'bearer' }); });
    expect(screen.queryByRole('button', { name: 'Account: assetk' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sign in' })).toHaveFocus();
  });
});
