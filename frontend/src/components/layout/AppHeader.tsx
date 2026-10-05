import { useEffect, useRef, useState } from 'react';
import { Brand } from '../Brand';
import { Button } from '../ui/Button';
import { Dialog } from '../ui/Dialog';
import { Icon } from '../ui/Icon';
import type { ReactNode } from 'react';

export function AppHeader({ onNewChat, account, onOpenHistory }: {
  onNewChat: () => void; account?: ReactNode; onOpenHistory?: (trigger: HTMLElement) => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [aboutOpen, setAboutOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const firstItemRef = useRef<HTMLButtonElement>(null);
  const aboutTriggerRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!menuOpen) return;
    firstItemRef.current?.focus();
    function dismissOutside(event: PointerEvent) {
      if (event.target instanceof Node && !menuRef.current?.contains(event.target)) setMenuOpen(false);
    }
    document.addEventListener('pointerdown', dismissOutside);
    const desktop = window.matchMedia('(min-width: 721px)');
    function dismissOnResize(event: MediaQueryListEvent) {
      if (event.matches) setMenuOpen(false);
    }
    desktop.addEventListener('change', dismissOnResize);
    return () => {
      document.removeEventListener('pointerdown', dismissOutside);
      desktop.removeEventListener('change', dismissOnResize);
    };
  }, [menuOpen]);

  function startNewChat() {
    setMenuOpen(false);
    onNewChat();
  }

  return (
    <header className="app-header">
      <button className="brand-home" aria-label="Go to welcome screen" onClick={startNewChat}>
        <Brand />
      </button>
      <div className="header-actions">
      <nav className="desktop-nav" aria-label="Primary navigation">
        <Button variant="quiet" className="nav-button" onClick={startNewChat}><Icon name="plus" />New chat</Button>
        <span className="nav-divider" aria-hidden="true" />
        <Button variant="quiet" className="nav-button" onClick={(event) => {
          aboutTriggerRef.current = event.currentTarget;
          setAboutOpen(true);
        }}>About</Button>
      </nav>
      <div className="mobile-nav" ref={menuRef} onKeyDown={(event) => {
        if (event.key === 'Escape' && menuOpen) {
          event.preventDefault();
          setMenuOpen(false);
          menuButtonRef.current?.focus();
        }
      }}>
        <Button ref={menuButtonRef} variant="glass" className="icon-button" aria-label="Navigation menu"
          aria-expanded={menuOpen} aria-controls="mobile-navigation" onClick={() => setMenuOpen(!menuOpen)}>
          <Icon name={menuOpen ? 'close' : 'menu'} />
        </Button>
        {menuOpen && (
          <nav className="mobile-nav__panel glass glass--smoked" aria-label="Mobile navigation" id="mobile-navigation">
            <Button ref={firstItemRef} variant="quiet" onClick={startNewChat}><Icon name="plus" />New chat</Button>
            {onOpenHistory && <Button variant="quiet" onClick={() => {
              setMenuOpen(false);
              if (menuButtonRef.current) onOpenHistory(menuButtonRef.current);
            }}><Icon name="history" />Saved chats</Button>}
            <Button variant="quiet" onClick={() => {
              aboutTriggerRef.current = menuButtonRef.current;
              setMenuOpen(false);
              setAboutOpen(true);
            }}><Icon name="info" />About</Button>
          </nav>
        )}
      </div>
      {account}
      </div>
      <Dialog open={aboutOpen} title="About Pole Position" returnFocusTo={aboutTriggerRef.current}
        onClose={() => setAboutOpen(false)}>
        <p>An independent way to explore the 2026 FIA Formula 1 regulations.</p>
        <p>Built around the original regulation excerpts. Always consult the official documents for authoritative guidance.</p>
        <span className="dialog__note">Guest chats are temporary and clear when you refresh.</span>
      </Dialog>
    </header>
  );
}
