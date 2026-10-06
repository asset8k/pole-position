import { useEffect, useRef, useState } from 'react';

// This is presentation only. The complete, validated answer already lives in
// chat state, so history, saving and new requests never see a truncated draft.
export function useAnswerReveal(content: string, animate: boolean) {
  const [visible, setVisible] = useState(() => animate && !window.matchMedia('(prefers-reduced-motion: reduce)').matches
    ? Math.min(24, content.length) : content.length);
  const stop = useRef<() => void>(() => {});

  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)');
    let timer: ReturnType<typeof setTimeout>;
    let cancelled = false;
    function finish() {
      clearTimeout(timer);
      if (!cancelled) setVisible(content.length);
    }
    stop.current = finish;
    if (!animate || media.matches || document.hidden) {
      finish();
      return () => { cancelled = true; };
    }
    const initial = Math.min(24, content.length);
    const duration = Math.min(3000, Math.max(750, content.length * 5));
    const started = Date.now();
    setVisible(initial);
    function tick() {
      if (cancelled) return;
      const progress = Math.min(1, (Date.now() - started) / duration);
      setVisible(Math.ceil(initial + (content.length - initial) * progress));
      if (progress < 1) timer = setTimeout(tick, 40);
    }
    function preferenceChanged() { if (media.matches) finish(); }
    function visibilityChanged() { if (document.hidden) finish(); }
    timer = setTimeout(tick, 40);
    media.addEventListener('change', preferenceChanged);
    document.addEventListener('visibilitychange', visibilityChanged);
    return () => {
      cancelled = true;
      clearTimeout(timer);
      media.removeEventListener('change', preferenceChanged);
      document.removeEventListener('visibilitychange', visibilityChanged);
    };
  }, [content, animate]);

  return { visible: animate ? visible : content.length, revealing: animate && visible < content.length,
    finish: () => stop.current() };
}
