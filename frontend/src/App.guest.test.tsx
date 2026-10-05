import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';

function deferredResponse() {
  let resolve!: (response: Response) => void;
  const promise = new Promise<Response>((accept) => { resolve = accept; });
  return { promise, resolve };
}

const response = (answer = 'Use at least two specifications. [S1]') => Response.json({
  answer, citations: [], conversation_id: null,
});

beforeEach(() => { vi.spyOn(globalThis, 'fetch').mockImplementation(async () => response()); });
afterEach(() => { vi.restoreAllMocks(); });

async function ask(question: string) {
  const user = userEvent.setup();
  await user.type(screen.getByRole('textbox'), question);
  await user.click(screen.getByRole('button', { name: 'Send question' }));
}

describe('guest chat integration', () => {
  it('uses the API layer and builds a follow-up from previous completed messages only', async () => {
    render(<App />);
    await ask('Tyres?');
    expect(await screen.findByText('Use at least two specifications. [S1]')).toBeInTheDocument();
    expect(screen.getByRole('textbox')).toHaveValue('');
    await ask('What if not?');
    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
    const calls = vi.mocked(globalThis.fetch).mock.calls;
    expect(calls[1][0]).toBe('/api/chat');
    expect(JSON.parse(String(calls[1][1]?.body))).toEqual({ message: 'What if not?', history: [
      { role: 'user', content: 'Tyres?' },
      { role: 'assistant', content: 'Use at least two specifications. [S1]' },
    ] });
    expect(new Headers(calls[1][1]?.headers).has('Authorization')).toBe(false);
    expect(screen.getByRole('log')).toHaveTextContent('Tyres?');
    expect(screen.getByRole('log')).toHaveTextContent('What if not?');
  });

  it('shows loading and blocks repeated submits before the answer arrives', async () => {
    const pending = deferredResponse();
    vi.mocked(globalThis.fetch).mockReturnValueOnce(pending.promise);
    render(<App />);
    await ask('Pending question');
    expect(screen.getByRole('status')).toHaveTextContent('Checking the regulations');
    expect(screen.getByRole('textbox')).toHaveAttribute('readonly');
    expect(screen.getByRole('button', { name: 'Send question' })).toBeDisabled();
    fireEvent.submit(screen.getByRole('form'));
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
    await act(async () => { pending.resolve(response()); });
    expect(await screen.findByText('Use at least two specifications. [S1]')).toBeInTheDocument();
    expect(screen.getByRole('textbox')).not.toHaveAttribute('readonly');
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('restores a network-failed draft and explicitly resends without adding a failed turn', async () => {
    vi.mocked(globalThis.fetch).mockRejectedValueOnce(new TypeError('Failed to fetch'));
    render(<App />);
    await ask('Retry question');
    expect(await screen.findByRole('alert')).toHaveTextContent('Unable to reach the server');
    expect(screen.getByRole('textbox')).toHaveValue('Retry question');
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
    await userEvent.setup().click(screen.getByRole('button', { name: 'Send question' }));
    expect(await screen.findByText('Use at least two specifications. [S1]')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(within(screen.getByRole('log')).getAllByText('Retry question')).toHaveLength(1);
    expect(JSON.parse(String(vi.mocked(globalThis.fetch).mock.calls[1][1]?.body))).toEqual({
      message: 'Retry question', history: [],
    });
  });

  it('handles an upstream server error without exposing internal details', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(Response.json({ detail: 'Private diagnostic' }, { status: 503 }));
    render(<App />);
    await ask('Question');
    expect(await screen.findByRole('alert')).toHaveTextContent('The server is unavailable');
    expect(screen.queryByText('Private diagnostic')).not.toBeInTheDocument();
    expect(screen.getByRole('textbox')).toHaveValue('Question');
  });

  it('New chat aborts pending work and ignores the late answer', async () => {
    const pending = deferredResponse();
    vi.mocked(globalThis.fetch).mockReturnValueOnce(pending.promise);
    render(<App />);
    await ask('Old question');
    const signal = vi.mocked(globalThis.fetch).mock.calls[0][1]?.signal;
    await userEvent.setup().click(within(screen.getByRole('navigation', { name: 'Primary navigation' }))
      .getByRole('button', { name: 'New chat' }));
    expect(signal?.aborted).toBe(true);
    expect(screen.getByRole('heading', { name: 'Know the rules.' })).toBeInTheDocument();
    expect(screen.getByRole('textbox')).toHaveFocus();
    await act(async () => { pending.resolve(response('Stale answer')); });
    expect(screen.queryByText('Stale answer')).not.toBeInTheDocument();
    await ask('Fresh question');
    expect(await screen.findByText('Use at least two specifications. [S1]')).toBeInTheDocument();
    expect(JSON.parse(String(vi.mocked(globalThis.fetch).mock.calls[1][1]?.body)).history).toEqual([]);
  });

  it('renders unanswerable responses normally and keeps HTML inert', async () => {
    const answer = 'Not enough evidence. <img src="x" onerror="alert(1)">';
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(response(answer));
    render(<App />);
    await ask('Unknown fact');
    expect(await screen.findByText(answer)).toBeInTheDocument();
    expect(screen.getByRole('log').querySelector('img')).toBeNull();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('does not steal focus from an open dialog when the answer arrives', async () => {
    const pending = deferredResponse();
    vi.mocked(globalThis.fetch).mockReturnValueOnce(pending.promise);
    render(<App />);
    await ask('Question');
    await userEvent.setup().click(screen.getByRole('button', { name: 'About' }));
    await act(async () => { pending.resolve(response()); });
    expect(await screen.findByText('Use at least two specifications. [S1]')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Close dialog' })).toHaveFocus();
  });
});
