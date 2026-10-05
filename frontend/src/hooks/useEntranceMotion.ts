import { useLayoutEffect } from 'react';
import type { RefObject } from 'react';

// Animate the live surface, not a retained copy of a conversation or form.
// Session boundaries still remove private content immediately.
export function useEntranceMotion(ref: RefObject<HTMLElement | null>, identity: string) {
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element?.animate || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const motion = element.animate([
      { opacity: 0, transform: 'translateY(8px)' },
      { opacity: 1, transform: 'translateY(0)' },
    ], { duration: 320, easing: 'cubic-bezier(.22, 1, .36, 1)' });
    return () => motion.cancel();
  }, [ref, identity]);
}
