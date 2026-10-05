import { useRef, useState } from 'react';
import type { FormEvent } from 'react';
import type { Session, AuthMode } from '../../auth/useSession';
import { AccountCreatedError, authErrorMessage } from '../../auth/useSession';
import { Button } from '../ui/Button';
import { Dialog } from '../ui/Dialog';
import { Input } from '../ui/Input';
import { useEntranceMotion } from '../../hooks/useEntranceMotion';

export function AuthDialog({ session, onClose, trigger }: {
  session: Session; onClose: () => void; trigger: HTMLElement | null;
}) {
  const [mode, setMode] = useState<AuthMode>('login');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [pending, setPending] = useState(false);
  const locked = useRef(false);
  const attempt = useRef(0);
  const formRef = useRef<HTMLFormElement>(null);
  useEntranceMotion(formRef, mode);
  const usernameError = /^[a-z0-9_]{3,50}$/.test(username) ? '' : 'Use 3–50 lowercase letters, numbers, or underscores.';
  const passwordError = password.length >= 8 ? '' : 'Use at least 8 characters.';

  function cancel() {
    attempt.current++;
    session.cancelAuthentication();
    setPassword('');
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (locked.current) return;
    setSubmitted(true);
    setError('');
    if (usernameError || passwordError) return;
    locked.current = true;
    setPending(true);
    const currentAttempt = ++attempt.current;
    try {
      await session.authenticate(mode, { username, password });
      if (attempt.current === currentAttempt) setPassword('');
      // Installing the session remounts the workspace and dismisses this form.
    } catch (cause) {
      if (attempt.current !== currentAttempt) return;
      setError(authErrorMessage(cause));
      if (cause instanceof AccountCreatedError) { setMode('login'); setPassword(''); setSubmitted(false); }
    } finally {
      if (attempt.current === currentAttempt) { locked.current = false; setPending(false); }
    }
  }

  return <Dialog open title={mode === 'login' ? 'Welcome back.' : 'Your place on the grid.'}
    closeLabel="Close sign in" returnFocusTo={trigger} onClose={onClose} onDismissStart={cancel}>
    <form ref={formRef} className="auth-form" onSubmit={(event) => { void submit(event); }} noValidate aria-busy={pending}>
      <p className="auth-form__intro">{mode === 'login' ? 'Sign in to keep your conversations.' : 'Create an account. Keep your conversations.'}</p>
      <Input label="Username" name="username" autoComplete="username" autoCapitalize="none" spellCheck={false}
        value={username} maxLength={50} readOnly={pending} error={submitted ? usernameError : undefined}
        onChange={(event) => { setUsername(event.target.value); setError(''); }} />
      <Input label="Password" name="password" type="password" autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
        value={password} readOnly={pending} error={submitted ? passwordError : undefined}
        hint={mode === 'register' ? 'At least 8 characters' : undefined}
        onChange={(event) => { setPassword(event.target.value); setError(''); }} />
      {error && <p className="auth-form__error" role="alert">{error}</p>}
      <Button type="submit" loading={pending} className="auth-form__submit">
        {pending ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}
      </Button>
      <div className="auth-form__switch">
        <span>{mode === 'login' ? 'New here?' : 'Already registered?'}</span>
        <Button variant="quiet" disabled={pending} onClick={() => {
          setMode(mode === 'login' ? 'register' : 'login');
          setPassword(''); setError(''); setSubmitted(false);
        }}>{mode === 'login' ? 'Create an account' : 'Sign in instead'}</Button>
      </div>
      <p className="auth-form__note">{mode === 'register' ? 'Guest messages won’t be imported into your account.' : 'Guest mode is always available.'}</p>
    </form>
  </Dialog>;
}
