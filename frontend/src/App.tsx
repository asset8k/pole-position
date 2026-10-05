import { useLayoutEffect, useRef, useState } from 'react';
import { useGuestChat } from './chat/useGuestChat';
import { ChatScreen } from './components/chat/ChatScreen';
import { AppHeader } from './components/layout/AppHeader';
import { WelcomeScreen } from './components/welcome/WelcomeScreen';

export function App() {
  const chat = useGuestChat();
  const [focusRequest, setFocusRequest] = useState(0);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const showWelcome = chat.messages.length === 0 && chat.activeTurn === null;

  useLayoutEffect(() => {
    if (focusRequest > 0) composerRef.current?.focus();
  }, [focusRequest]);

  function newChat() {
    chat.newChat();
    setFocusRequest((request) => request + 1);
  }

  function selectSuggestion(value: string) {
    chat.updateDraft(value);
    composerRef.current?.focus();
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#question">Skip to question</a>
      <div className="ambient" aria-hidden="true">
        <div className="ambient__ribbon" />
      </div>
      <AppHeader onNewChat={newChat} />
      <main className={`app-main${showWelcome ? '' : ' app-main--chat'}`} id="main-content">
        {showWelcome ? <WelcomeScreen
          question={chat.draft}
          composerRef={composerRef}
          onChange={chat.updateDraft}
          onSuggestion={selectSuggestion}
          onSubmit={chat.send}
        /> : <ChatScreen messages={chat.messages} activeTurn={chat.activeTurn} draft={chat.draft}
          composerRef={composerRef} onChange={chat.updateDraft} onSubmit={chat.send} />}
      </main>
      <footer className="app-footer">
        <span>Independent project. Not affiliated with FIA or Formula 1.</span>
        <span className="app-footer__edition">2026 EDITION</span>
      </footer>
    </div>
  );
}
