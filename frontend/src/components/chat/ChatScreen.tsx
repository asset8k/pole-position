import { useEffect, useState } from 'react';
import type { RefObject } from 'react';
import type { ActiveTurn, GuestMessage } from '../../chat/useGuestChat';
import { Composer } from '../welcome/Composer';
import { AnswerContent } from './AnswerContent';
import { SourceDrawer } from './SourceDrawer';
import type { SelectedSource } from './SourceDrawer';
import { useChatScroll } from '../../chat/useChatScroll';
import { Button } from '../ui/Button';

interface ChatScreenProps {
  messages: GuestMessage[];
  activeTurn: ActiveTurn | null;
  draft: string;
  composerRef: RefObject<HTMLTextAreaElement | null>;
  onChange: (value: string) => void;
  onSubmit: (question: string) => void;
  authenticated?: boolean;
  title?: string;
}

export function ChatScreen({ messages, activeTurn, draft, composerRef, onChange, onSubmit, authenticated = false, title = 'Regulation chat' }: ChatScreenProps) {
  const { bottomRef, hasNewMessages, jumpToLatest } = useChatScroll(messages.length, activeTurn?.status);
  const isPending = activeTurn?.status === 'loading';
  const [selectedSource, setSelectedSource] = useState<SelectedSource | null>(null);
  const selection = selectedSource && messages.some((message) => message.id === selectedSource.messageId)
    ? selectedSource : null;

  useEffect(() => {
    if (document.querySelector('dialog[open]')) return;
    // Don't take focus from navigation or an open About dialog when a reply lands.
    if (!isPending && !hasNewMessages && document.activeElement === document.body) composerRef.current?.focus({ preventScroll: true });
  }, [messages.length, activeTurn?.status, isPending, hasNewMessages, composerRef]);

  return (
    <section className="chat-screen" aria-labelledby="chat-title">
      <div className="chat-heading">
        <h1 id="chat-title">{title}</h1>
        <span className="chat-heading__guest">{authenticated ? 'Saved to your account' : <>Guest <span aria-hidden="true">·</span> Clears on refresh</>}</span>
      </div>
      <div role="log" aria-label="Conversation messages" aria-live="polite" aria-relevant="additions">
        <ol className="chat-messages">
          {messages.map((message) => (
            <li key={message.id} className={`chat-message chat-message--${message.role}`}>
              <span className="chat-message__author">{message.role === 'user' ? 'You' : 'Pole Position'}</span>
              {message.role === 'assistant'
                ? <AnswerContent content={message.content} citations={message.citations}
                    onOpenSource={(source, trigger) => setSelectedSource({ messageId: message.id, source, trigger })} />
                : <p className="chat-message__text">{message.content}</p>}
            </li>
          ))}
          {activeTurn && (
            <li className="chat-message chat-message--user">
              <span className="chat-message__author">You</span>
              <p className="chat-message__text">{activeTurn.question}</p>
            </li>
          )}
        </ol>
      </div>
      {isPending && <p className="chat-loading" role="status"><span className="spinner" aria-hidden="true" />Checking the regulations…</p>}
      {activeTurn?.status === 'error' && (
        <div className="chat-error" role="alert">
          <p>{activeTurn.error}</p><span>Your question is ready to send again.</span>
        </div>
      )}
      <div className="chat-composer">
        {hasNewMessages && <div className="chat-jump"><Button variant="glass" onClick={() => {
          jumpToLatest(); composerRef.current?.focus({ preventScroll: true });
        }}>Jump to latest</Button></div>}
        <Composer value={draft} inputRef={composerRef} onChange={onChange} onSubmit={onSubmit} pending={isPending} />
      </div>
      <div ref={bottomRef} />
      {selection && <SourceDrawer key={`${selection.messageId}:${selection.source.source_id}`}
        selection={selection} onClose={() => setSelectedSource(null)} />}
    </section>
  );
}
