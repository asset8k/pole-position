import { act, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useChatScroll } from './useChatScroll';

function Harness({ count, status }: { count: number; status?: string }) {
  const { bottomRef, hasNewMessages, jumpToLatest } = useChatScroll(count, status);
  return <><div ref={bottomRef} data-testid="bottom" />{hasNewMessages && <button onClick={jumpToLatest}>Jump</button>}</>;
}
const previousScroll = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollIntoView');
afterEach(() => {
  vi.restoreAllMocks(); vi.unstubAllGlobals();
  if (previousScroll) Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', previousScroll);
  else Reflect.deleteProperty(HTMLElement.prototype, 'scrollIntoView');
});

function setup() {
  let top = 700;
  vi.stubGlobal('innerHeight', 800);
  vi.stubGlobal('visualViewport', undefined);
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(() => ({ top }) as DOMRect);
  const scroll = vi.fn();
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: scroll });
  const position = (next: number) => act(() => { top = next; window.dispatchEvent(new Event('scroll')); });
  return { scroll, position };
}

describe('chat scroll intent', () => {
  it('follows new turns near the bottom but preserves older reading position until requested', () => {
    const { scroll, position } = setup();
    const view = render(<Harness count={2} />);
    view.rerender(<Harness count={2} status="loading" />);
    position(1500); // User scrolls up while a reply is pending.
    scroll.mockClear();
    view.rerender(<Harness count={4} />);
    expect(scroll).not.toHaveBeenCalled();
    act(() => screen.getByRole('button', { name: 'Jump' }).click());
    expect(scroll).toHaveBeenCalledWith({ block: 'end', behavior: 'auto' });
    expect(screen.queryByRole('button')).toBeNull();
    position(700);
    view.rerender(<Harness count={6} />);
    expect(scroll).toHaveBeenCalledTimes(2);
  });

  it('explicit sending follows again; open dialogs prevent background scrolling', () => {
    const { scroll, position } = setup();
    const view = render(<Harness count={2} />);
    position(1600);
    scroll.mockClear();
    view.rerender(<Harness count={2} status="loading" />);
    expect(scroll).toHaveBeenCalledTimes(1);
    const dialog = document.createElement('dialog');
    dialog.open = true; document.body.append(dialog);
    scroll.mockClear();
    view.rerender(<Harness count={4} />);
    expect(scroll).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Jump' })).toBeInTheDocument();
    dialog.remove();
  });
});
