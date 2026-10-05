import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';

export function useChatScroll(messageCount: number, turnStatus: string | undefined) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const following = useRef(true);
  const previous = useRef({ messageCount, turnStatus });
  const [hasNewMessages, setHasNewMessages] = useState(false);

  const jumpToLatest = useCallback(() => {
    following.current = true;
    setHasNewMessages(false);
    bottomRef.current?.scrollIntoView?.({ block: 'end', behavior: 'auto' });
  }, []);

  useEffect(() => {
    function trackPosition() {
      if (document.querySelector('dialog[open]')) return;
      const bottom = bottomRef.current?.getBoundingClientRect().top;
      const visibleBottom = window.visualViewport
        ? window.visualViewport.height + window.visualViewport.offsetTop : window.innerHeight;
      following.current = bottom === undefined || bottom <= visibleBottom + 80;
      if (following.current) setHasNewMessages(false);
    }
    window.addEventListener('scroll', trackPosition, { passive: true });
    return () => window.removeEventListener('scroll', trackPosition);
  }, []);

  useLayoutEffect(() => {
    const sent = turnStatus === 'loading' && previous.current.turnStatus !== 'loading';
    const appended = messageCount > previous.current.messageCount;
    previous.current = { messageCount, turnStatus };
    if (sent) following.current = true; // Sending is an explicit request to go to the current turn.
    if (!document.querySelector('dialog[open]') && following.current) jumpToLatest();
    else if (appended) setHasNewMessages(true);
  }, [messageCount, turnStatus, jumpToLatest]);

  return { bottomRef, hasNewMessages, jumpToLatest };
}
