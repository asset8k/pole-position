import { useLayoutEffect, useRef, useState } from 'react';
import { useChat } from './chat/useGuestChat';
import { useSession } from './auth/useSession';
import type { Session } from './auth/useSession';
import { AuthDialog } from './components/auth/AuthDialog';
import { AccountControl } from './components/auth/AccountControl';
import { Button } from './components/ui/Button';
import { ChatScreen } from './components/chat/ChatScreen';
import { AppHeader } from './components/layout/AppHeader';
import { WelcomeScreen } from './components/welcome/WelcomeScreen';
import { useSavedConversations } from './chat/useSavedConversations';
import { ConversationList } from './components/chat/ConversationList';
import type { ConversationAction } from './components/chat/ConversationList';
import { ConversationActionDialog } from './components/chat/ConversationActionDialog';
import { Dialog } from './components/ui/Dialog';
import { useVisualViewport } from './hooks/useVisualViewport';

export function App() {
  useVisualViewport();
  const session = useSession();
  // Session boundaries unmount all messages, drafts, sources, and pending work.
  // Saved data comes from ownership-checked API endpoints, not browser storage.
  return <Workspace key={session.token ?? session.status} session={session} />;
}

function Workspace({ session }: { session: Session }) {
  const saved = useSavedConversations(session.token);
  const chat = useChat({ token: session.token, onSaved: () => { void saved.reload(); }, onMissing: saved.remove });
  const [authTrigger, setAuthTrigger] = useState<HTMLElement | null>(null);
  const [historyTrigger, setHistoryTrigger] = useState<HTMLElement | null>(null);
  const historyReturn = useRef<HTMLElement | null>(null);
  const managementFromMobile = useRef(false);
  const [action, setAction] = useState<ConversationAction | null>(null);
  const [focusRequest, setFocusRequest] = useState(0);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const mainRef = useRef<HTMLElement>(null);
  const authenticated = session.status === 'authenticated';
  const showWelcome = chat.selectedId === null && chat.messages.length === 0 && chat.activeTurn === null;
  const selected = saved.items.find((item) => item.id === chat.selectedId);

  useLayoutEffect(() => {
    if (focusRequest > 0) (composerRef.current ?? mainRef.current)?.focus();
  }, [focusRequest]);

  function newChat() {
    setHistoryTrigger(null);
    chat.newChat();
    setFocusRequest((request) => request + 1);
  }

  async function openConversation(id: number) {
    setHistoryTrigger(null);
    if (await chat.openConversation(id)) setFocusRequest((request) => request + 1);
  }

  function manage(next: ConversationAction) {
    managementFromMobile.current = historyTrigger !== null;
    setAction(historyTrigger ? { ...next, trigger: historyTrigger } : next);
    setHistoryTrigger(null);
  }

  function closeAction() {
    setAction(null);
    if (managementFromMobile.current) setHistoryTrigger(historyReturn.current);
  }

  const conversationList = <ConversationList saved={saved} selectedId={chat.selectedId}
    onOpen={(id) => { void openConversation(id); }} onNewChat={newChat} onManage={manage} />;

  function selectSuggestion(value: string) {
    chat.updateDraft(value);
    composerRef.current?.focus();
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href={chat.loadState || ['restoring', 'unavailable'].includes(session.status) ? '#main-content' : '#question'}>
        {chat.loadState || ['restoring', 'unavailable'].includes(session.status) ? 'Skip to main content' : 'Skip to question'}
      </a>
      <div className="ambient" aria-hidden="true">
        <div className="ambient__ribbon" />
      </div>
      <AppHeader onNewChat={newChat} account={<AccountControl session={session} onSignIn={setAuthTrigger} />}
        onOpenHistory={authenticated ? (trigger) => { historyReturn.current = trigger; setHistoryTrigger(trigger); } : undefined} />
      {session.notice && <p className="session-notice" role="alert">{session.notice}</p>}
      <div className={`workspace-layout${authenticated ? ' workspace-layout--saved' : ''}`}>
      {authenticated && <aside className="conversation-sidebar glass glass--smoked" aria-label="Your saved chats">{conversationList}</aside>}
      <main ref={mainRef} tabIndex={-1} className={`app-main${showWelcome ? '' : ' app-main--chat'}`} id="main-content">
        {session.status === 'restoring' || session.status === 'unavailable' ? <section className="session-check" aria-label="Session verification">
          {session.status === 'restoring' ? <p role="status"><span className="spinner" aria-hidden="true" />Checking your session…</p>
            : <><h1>Let’s reconnect.</h1><div><Button onClick={() => { void session.restore(); }}>Retry</Button>
              <Button variant="quiet" onClick={() => session.logout()}>Continue as guest</Button></div></>}
        </section> : chat.loadState ? <section className="conversation-loading" aria-label="Conversation loading">
          {chat.loadState.status === 'loading' ? <p role="status"><span className="spinner" aria-hidden="true" />Opening conversation…</p>
            : <><p role="alert">{chat.loadState.error}</p><div>
              <Button onClick={() => { if (chat.selectedId) void openConversation(chat.selectedId); }}>Retry conversation</Button>
              <Button variant="quiet" onClick={newChat}>Start a new chat</Button></div></>}
        </section> : showWelcome ? <WelcomeScreen
          question={chat.draft}
          composerRef={composerRef}
          onChange={chat.updateDraft}
          onSuggestion={selectSuggestion}
          onSubmit={chat.send}
          authenticated={authenticated}
        /> : <ChatScreen key={chat.selectedId ?? 'new'} messages={chat.messages} activeTurn={chat.activeTurn} draft={chat.draft}
          composerRef={composerRef} onChange={chat.updateDraft} onSubmit={chat.send} authenticated={authenticated} title={selected?.title} />}
      </main>
      </div>
      <footer className="app-footer">
        <span>Independent project. Not affiliated with FIA or Formula 1.</span>
        <span className="app-footer__edition">2026 EDITION</span>
      </footer>
      {authTrigger && <AuthDialog session={session} trigger={authTrigger} onClose={() => setAuthTrigger(null)} />}
      {historyTrigger && <Dialog open title="Saved chats" closeLabel="Close saved chats" returnFocusTo={historyTrigger}
        onClose={() => setHistoryTrigger(null)}>{conversationList}</Dialog>}
      {action && <ConversationActionDialog key={`${action.kind}:${action.item.id}`} action={action} saved={saved} onClose={closeAction}
        onDeleted={(id) => { if (chat.selectedId === id) newChat(); else setFocusRequest((request) => request + 1); }} />}
    </div>
  );
}
