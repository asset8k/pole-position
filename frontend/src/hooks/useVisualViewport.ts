import { useEffect } from 'react';

// Layout viewport and visible viewport can differ with an on-screen keyboard.
// CSS handles ordinary resize; these insets handle visual-only resize. Pinch
// zoom is left to the browser, never interpreted as an on-screen keyboard.
export function useVisualViewport() {
  useEffect(() => {
    const root = document.documentElement;
    const viewport = window.visualViewport;
    const names = ['--visual-height', '--visual-top', '--visual-bottom'];
    const previous = names.map((name) => root.style.getPropertyValue(name));
    let frame = 0;
    function update() {
      const unzoomed = !viewport || Math.abs(viewport.scale - 1) < .05;
      const height = unzoomed ? viewport?.height ?? window.innerHeight : window.innerHeight;
      const top = unzoomed ? viewport?.offsetTop ?? 0 : 0;
      const bottom = Math.max(0, window.innerHeight - height - top);
      root.style.setProperty('--visual-height', `${height}px`);
      root.style.setProperty('--visual-top', `${top}px`);
      root.style.setProperty('--visual-bottom', `${bottom}px`);
      cancelAnimationFrame(frame);
      const active = document.activeElement;
      if (unzoomed && bottom > 80 && active instanceof HTMLElement && active.matches('input, textarea')) {
        frame = requestAnimationFrame(() => {
          if (active.isConnected && document.activeElement === active) {
            (active.closest('.composer') ?? active).scrollIntoView?.({ block: 'nearest', behavior: 'auto' });
          }
        });
      }
    }
    update();
    viewport?.addEventListener('resize', update);
    viewport?.addEventListener('scroll', update);
    window.addEventListener('resize', update);
    document.addEventListener('focusin', update);
    return () => {
      cancelAnimationFrame(frame);
      viewport?.removeEventListener('resize', update);
      viewport?.removeEventListener('scroll', update);
      window.removeEventListener('resize', update);
      document.removeEventListener('focusin', update);
      names.forEach((name, index) => previous[index] ? root.style.setProperty(name, previous[index]) : root.style.removeProperty(name));
    };
  }, []);
}
