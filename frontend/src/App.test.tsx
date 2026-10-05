import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';
import { api } from './api/endpoints';
import { suggestions } from './components/welcome/suggestions';

beforeEach(() => {
  vi.spyOn(api.chat, 'send').mockResolvedValue({ answer: 'A grounded answer.', citations: [], conversation_id: null });
});
afterEach(() => { vi.restoreAllMocks(); });

describe('welcome screen', () => {
  it('mounts the brand, composer, compact suggestions, and guest notice', () => {
    render(<App />);
    expect(screen.getByRole('img', { name: 'Pole Position' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Know the rules.');
    expect(screen.getByRole('textbox', { name: 'Your question' })).toHaveValue('');
    expect(within(screen.getByRole('list', { name: 'Suggested questions' })).getAllByRole('button')).toHaveLength(3);
    expect(screen.getByRole('status')).toHaveTextContent('Clears on refresh');
  });

  it.each(suggestions)('$label populates the composer without submitting', async (suggestion) => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole('button', { name: suggestion.label }));
    const input = screen.getByRole('textbox');
    expect(input).toHaveValue(suggestion.question);
    expect(input).toHaveFocus();
    expect(api.chat.send).not.toHaveBeenCalled();
  });

  it('disables blank sending and sends a question into the guest transcript', async () => {
    const user = userEvent.setup();
    render(<App />);
    const input = screen.getByRole('textbox');
    const send = screen.getByRole('button', { name: 'Send question' });
    expect(send).toBeDisabled();
    await user.type(input, '   ');
    expect(send).toBeDisabled();
    await user.type(input, 'What is the tyre rule?');
    await user.click(send);
    expect(await screen.findByText('A grounded answer.')).toBeInTheDocument();
    expect(screen.getByRole('log')).toHaveTextContent('What is the tyre rule?');
    expect(api.chat.send).toHaveBeenCalledWith({ message: 'What is the tyre rule?', history: [] }, { signal: expect.any(AbortSignal) });
  });

  it('new chat clears the draft and notice and focuses the composer', async () => {
    const user = userEvent.setup();
    render(<App />);
    const input = screen.getByRole('textbox');
    await user.type(input, 'A question{Enter}');
    await user.click(within(screen.getByRole('navigation', { name: 'Primary navigation' })).getByRole('button', { name: 'New chat' }));
    expect(screen.getByRole('textbox')).toHaveValue('');
    expect(screen.getByRole('textbox')).toHaveFocus();
    expect(screen.getByRole('heading', { name: 'Know the rules.' })).toBeInTheDocument();
  });

  it('the brand returns to an empty welcome composer', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.type(screen.getByRole('textbox'), 'A question');
    await user.click(screen.getByRole('button', { name: 'Go to welcome screen' }));
    expect(screen.getByRole('textbox')).toHaveValue('');
    expect(screen.getByRole('textbox')).toHaveFocus();
  });

  it('about opens an accessible dialog and restores focus on close or native cancel', async () => {
    const user = userEvent.setup();
    render(<App />);
    const about = screen.getByRole('button', { name: 'About' });
    await user.click(about);
    expect(screen.getByRole('dialog', { name: 'About Pole Position' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Close dialog' })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole('button', { name: 'Close dialog' })).toHaveFocus();
    await user.tab({ shift: true });
    expect(screen.getByRole('button', { name: 'Close dialog' })).toHaveFocus();
    await user.click(screen.getByRole('button', { name: 'Close dialog' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(about).toHaveFocus();
    await user.click(about);
    fireEvent(screen.getByRole('dialog'), new Event('cancel', { cancelable: true, bubbles: true }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(about).toHaveFocus();
  });
});

describe('mobile navigation', () => {
  it('opens with focus, closes on Escape, and returns focus to its trigger', async () => {
    const user = userEvent.setup();
    render(<App />);
    const trigger = screen.getByRole('button', { name: 'Navigation menu' });
    await user.click(trigger);
    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    const navigation = screen.getByRole('navigation', { name: 'Mobile navigation' });
    expect(within(navigation).getByRole('button', { name: 'New chat' })).toHaveFocus();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('navigation', { name: 'Mobile navigation' })).not.toBeInTheDocument();
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    expect(trigger).toHaveFocus();
  });

  it('dismisses when the user clicks outside the navigation', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole('button', { name: 'Navigation menu' }));
    await user.click(screen.getByRole('textbox'));
    expect(screen.queryByRole('navigation', { name: 'Mobile navigation' })).not.toBeInTheDocument();
    expect(screen.getByRole('textbox')).toHaveFocus();
  });

  it('mobile new chat resets the composer and closes navigation', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.type(screen.getByRole('textbox'), 'A draft');
    await user.click(screen.getByRole('button', { name: 'Navigation menu' }));
    await user.click(within(screen.getByRole('navigation', { name: 'Mobile navigation' })).getByRole('button', { name: 'New chat' }));
    expect(screen.queryByRole('navigation', { name: 'Mobile navigation' })).not.toBeInTheDocument();
    expect(screen.getByRole('textbox')).toHaveValue('');
    expect(screen.getByRole('textbox')).toHaveFocus();
  });

  it('mobile about closes navigation and restores focus to its persistent trigger', async () => {
    const user = userEvent.setup();
    render(<App />);
    const trigger = screen.getByRole('button', { name: 'Navigation menu' });
    await user.click(trigger);
    await user.click(within(screen.getByRole('navigation', { name: 'Mobile navigation' })).getByRole('button', { name: 'About' }));
    expect(screen.queryByRole('navigation', { name: 'Mobile navigation' })).not.toBeInTheDocument();
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Close dialog' }));
    expect(trigger).toHaveFocus();
  });
});
