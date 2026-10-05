import { renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useEntranceMotion } from './useEntranceMotion';

afterEach(() => vi.restoreAllMocks());

describe('screen entrance motion', () => {
  it('animates a changed screen, not typing; cancels on navigation and unmount', () => {
    const cancel = vi.fn();
    const animate = vi.fn(() => ({ cancel }));
    const element = document.createElement('main');
    Object.defineProperty(element, 'animate', { value: animate });
    const ref = { current: element };
    const { rerender, unmount } = renderHook(({ screen }) => useEntranceMotion(ref, screen),
      { initialProps: { screen: 'welcome' } });
    expect(animate).toHaveBeenCalledOnce();
    expect(animate).toHaveBeenCalledWith([
      { opacity: 0, transform: 'translateY(8px)' },
      { opacity: 1, transform: 'translateY(0)' },
    ], { duration: 320, easing: 'cubic-bezier(.22, 1, .36, 1)' });
    rerender({ screen: 'welcome' });
    expect(animate).toHaveBeenCalledOnce();
    rerender({ screen: 'chat:2' });
    expect(cancel).toHaveBeenCalledOnce();
    expect(animate).toHaveBeenCalledTimes(2);
    unmount();
    expect(cancel).toHaveBeenCalledTimes(2);
  });

  it('skips motion for reduced-motion users', () => {
    vi.spyOn(window, 'matchMedia').mockImplementation((query) => ({
      media: query, matches: query === '(prefers-reduced-motion: reduce)',
    } as MediaQueryList));
    const animate = vi.fn();
    const element = document.createElement('main');
    Object.defineProperty(element, 'animate', { value: animate });
    renderHook(() => useEntranceMotion({ current: element }, 'welcome'));
    expect(animate).not.toHaveBeenCalled();
  });

  it('works without Web Animations or a mounted surface', () => {
    expect(() => renderHook(() => useEntranceMotion({ current: null }, 'welcome'))).not.toThrow();
    const element = document.createElement('main');
    expect(() => renderHook(() => useEntranceMotion({ current: element }, 'welcome'))).not.toThrow();
  });
});
