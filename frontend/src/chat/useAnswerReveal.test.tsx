import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useAnswerReveal } from './useAnswerReveal';

beforeEach(() => vi.useFakeTimers());
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

describe('answer presentation timing', () => {
  it('reveals a new answer progressively and caps even very long answers at 3 seconds', () => {
    const content = 'A complete validated answer. '.repeat(1000);
    const { result } = renderHook(() => useAnswerReveal(content, true));
    expect(result.current.visible).toBe(24);
    expect(result.current.revealing).toBe(true);
    act(() => vi.advanceTimersByTime(400));
    expect(result.current.visible).toBeGreaterThan(24);
    expect(result.current.visible).toBeLessThan(content.length);
    act(() => vi.advanceTimersByTime(2000));
    expect(result.current.revealing).toBe(true);
    expect(result.current.visible).toBeLessThan(content.length);
    act(() => vi.advanceTimersByTime(600));
    expect(result.current.visible).toBe(content.length);
    expect(result.current.revealing).toBe(false);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('loaded answers are instant and skip immediately finishes without pending ticks', () => {
    const content = 'An answer that is long enough to animate. '.repeat(4);
    const view = renderHook(({ animate }) => useAnswerReveal(content, animate), { initialProps: { animate: false } });
    expect(view.result.current.visible).toBe(content.length);
    expect(vi.getTimerCount()).toBe(0);
    view.rerender({ animate: true });
    act(() => view.result.current.finish());
    expect(view.result.current.revealing).toBe(false);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('cleans up timers on navigation and unmount', () => {
    const view = renderHook(({ content, animate }) => useAnswerReveal(content, animate),
      { initialProps: { content: 'First answer. '.repeat(100), animate: true } });
    view.rerender({ content: 'Saved answer', animate: false });
    expect(view.result.current.visible).toBe('Saved answer'.length);
    expect(vi.getTimerCount()).toBe(0);
    view.rerender({ content: 'New answer. '.repeat(100), animate: true });
    expect(vi.getTimerCount()).toBe(1);
    view.unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('respects reduced motion initially and when the preference changes', () => {
    const media = { ...window.matchMedia('(prefers-reduced-motion: reduce)'), matches: true };
    vi.spyOn(window, 'matchMedia').mockReturnValue(media);
    media.matches = true;
    const content = 'No motion should delay this answer. '.repeat(20);
    const reduced = renderHook(() => useAnswerReveal(content, true));
    expect(reduced.result.current.revealing).toBe(false);
    reduced.unmount();
    media.matches = false;
    const animated = renderHook(() => useAnswerReveal(content, true));
    const listener = vi.mocked(media.addEventListener).mock.calls.at(-1)![1] as () => void;
    act(() => { media.matches = true; listener(); });
    expect(animated.result.current.revealing).toBe(false);
    expect(vi.getTimerCount()).toBe(0);
  });
});
