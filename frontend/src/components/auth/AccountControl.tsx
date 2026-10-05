import { useEffect, useRef, useState } from 'react';
import type { Session } from '../../auth/useSession';
import { Button } from '../ui/Button';

export function AccountControl({ session, onSignIn }: {
  session: Session; onSignIn: (trigger: HTMLElement) => void;
}) {
  const [open, setOpen] = useState(false);
  const container = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const logout = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    logout.current?.focus();
    function outside(event: PointerEvent) {
      if (event.target instanceof Node && !container.current?.contains(event.target)) setOpen(false);
    }
    document.addEventListener('pointerdown', outside);
    return () => document.removeEventListener('pointerdown', outside);
  }, [open]);
  if (!session.user) return <Button variant="glass" className="sign-in-trigger"
    disabled={session.status !== 'guest'} onClick={(event) => onSignIn(event.currentTarget)}>Sign in</Button>;

  return <div className="account-control" ref={container}
    onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false); }}
    onKeyDown={(event) => {
      if (event.key === 'Escape') { event.preventDefault(); setOpen(false); trigger.current?.focus(); }
    }}>
    <Button ref={trigger} variant="glass" className="account-trigger" aria-label={`Account: ${session.user.username}`}
      aria-expanded={open} aria-controls="account-panel" onClick={() => setOpen(!open)}>
      <span className="account-avatar" aria-hidden="true">{session.user.username.slice(0, 1).toUpperCase()}</span>
      <span className="account-trigger__name">{session.user.username}</span>
    </Button>
    <section id="account-panel" className="account-panel glass glass--smoked" aria-label="Your account" hidden={!open} inert={!open || undefined}>
      <span className="account-panel__label">SIGNED IN AS</span>
      <p className="account-panel__username">{session.user.username}</p>
      <div className="account-panel__actions">
        <Button ref={logout} variant="quiet" onClick={() => session.logout('Signed out. Your saved conversations remain in your account.')}>Sign out</Button>
      </div>
    </section>
  </div>;
}
