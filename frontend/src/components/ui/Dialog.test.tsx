import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Dialog } from './Dialog';

afterEach(() => vi.restoreAllMocks());

function mockExit(dialog: HTMLElement) {
  let finish!: () => void;
  const finished = new Promise<void>((resolve) => { finish = resolve; });
  const cancel = vi.fn();
  const animate = vi.fn(() => ({ finished, cancel }));
  Object.defineProperty(dialog, 'animate', { value: animate });
  return { finish, cancel, animate };
}

describe('dialog dismissal motion', () => {
  it('cancels pending work immediately and dismisses only once after the exit', async () => {
    const onClose = vi.fn();
    const onDismissStart = vi.fn();
    render(<Dialog open title="Sign in" onClose={onClose} onDismissStart={onDismissStart}><p>Form</p></Dialog>);
    const dialog = screen.getByRole('dialog');
    const exit = mockExit(dialog);
    const close = screen.getByRole('button', { name: 'Close dialog' });
    fireEvent.click(close);
    fireEvent.click(close);
    expect(onDismissStart).toHaveBeenCalledOnce();
    expect(onClose).not.toHaveBeenCalled();
    expect(dialog).toHaveAttribute('data-closing', 'true');
    expect(dialog.querySelector('.dialog__content')).toHaveAttribute('inert');
    await act(async () => exit.finish());
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('unmounting cancels the exit and never invokes a stale close callback', async () => {
    const onClose = vi.fn();
    const { unmount } = render(<Dialog open title="Source" onClose={onClose}><p>Private excerpt</p></Dialog>);
    const exit = mockExit(screen.getByRole('dialog'));
    fireEvent.click(screen.getByRole('button', { name: 'Close dialog' }));
    unmount();
    await act(async () => exit.finish());
    expect(exit.cancel).toHaveBeenCalledOnce();
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.queryByText('Private excerpt')).not.toBeInTheDocument();
    expect(document.documentElement.style.overflow).toBe('');
  });

  it('reduced motion closes synchronously with no animation', () => {
    vi.spyOn(window, 'matchMedia').mockImplementation((query) => ({
      media: query, matches: true,
    } as MediaQueryList));
    const onClose = vi.fn();
    render(<Dialog open title="Source" onClose={onClose}><p>Excerpt</p></Dialog>);
    const exit = mockExit(screen.getByRole('dialog'));
    fireEvent(screen.getByRole('dialog'), new Event('cancel', { cancelable: true, bubbles: true }));
    expect(onClose).toHaveBeenCalledOnce();
    expect(exit.animate).not.toHaveBeenCalled();
  });
});
