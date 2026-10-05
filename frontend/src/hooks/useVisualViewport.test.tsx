import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useVisualViewport } from './useVisualViewport';

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

function viewport() {
  const value = Object.assign(new EventTarget(), { height: 500, offsetTop: 20, scale: 1 });
  vi.stubGlobal('visualViewport', value);
  vi.stubGlobal('innerHeight', 900);
  return value;
}

describe('visible viewport', () => {
  it('tracks keyboard-like insets and restores existing root values on cleanup', () => {
    const value = viewport();
    const style = document.documentElement.style;
    style.setProperty('--visual-height', '123px');
    const { unmount } = renderHook(useVisualViewport);
    expect(style.getPropertyValue('--visual-height')).toBe('500px');
    expect(style.getPropertyValue('--visual-top')).toBe('20px');
    expect(style.getPropertyValue('--visual-bottom')).toBe('380px');
    act(() => { value.height = 650; value.offsetTop = 0; value.dispatchEvent(new Event('resize')); });
    expect(style.getPropertyValue('--visual-bottom')).toBe('250px');
    unmount();
    expect(style.getPropertyValue('--visual-height')).toBe('123px');
    expect(style.getPropertyValue('--visual-bottom')).toBe('');
    value.dispatchEvent(new Event('resize'));
    expect(style.getPropertyValue('--visual-height')).toBe('123px');
    style.removeProperty('--visual-height');
  });

  it('does not treat pinch zoom as a keyboard and falls back without the API', () => {
    const value = viewport();
    value.scale = 2;
    const first = renderHook(useVisualViewport);
    expect(document.documentElement.style.getPropertyValue('--visual-height')).toBe('900px');
    expect(document.documentElement.style.getPropertyValue('--visual-bottom')).toBe('0px');
    first.unmount();
    vi.stubGlobal('visualViewport', undefined);
    const second = renderHook(useVisualViewport);
    act(() => { vi.stubGlobal('innerHeight', 700); window.dispatchEvent(new Event('resize')); });
    expect(document.documentElement.style.getPropertyValue('--visual-height')).toBe('700px');
    second.unmount();
  });

  it('keeps only the focused input visible and cancels queued work on unmount', () => {
    const value = viewport();
    let frame: FrameRequestCallback | undefined;
    vi.stubGlobal('requestAnimationFrame', vi.fn((callback: FrameRequestCallback) => { frame = callback; return 42; }));
    const cancel = vi.fn();
    vi.stubGlobal('cancelAnimationFrame', cancel);
    const input = document.createElement('input');
    const scroll = vi.fn();
    input.scrollIntoView = scroll;
    document.body.append(input);
    input.focus();
    const { unmount } = renderHook(useVisualViewport);
    act(() => { frame?.(0); });
    expect(scroll).toHaveBeenCalledWith({ block: 'nearest', behavior: 'auto' });
    act(() => { value.dispatchEvent(new Event('scroll')); });
    input.blur();
    act(() => { frame?.(0); });
    expect(scroll).toHaveBeenCalledTimes(1);
    unmount();
    expect(cancel).toHaveBeenCalledWith(42);
    input.remove();
  });
});
