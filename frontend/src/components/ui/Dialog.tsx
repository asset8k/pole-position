import { useEffect, useId, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Button } from './Button';
import { Icon } from './Icon';

type DialogProps = {
  open: boolean;
  title: string;
  children: ReactNode;
  onClose: () => void;
  returnFocusTo?: HTMLElement | null;
  variant?: 'dialog' | 'drawer';
  closeLabel?: string;
  footer?: ReactNode;
  onDismissStart?: () => void;
};

export function Dialog({ open, title, children, onClose, returnFocusTo, variant = 'dialog', closeLabel = 'Close dialog', footer, onDismissStart }: DialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const bodyId = useId();
  const [closing, setClosing] = useState(false);
  const exitRef = useRef<Animation | null>(null);
  const dismissRef = useRef({ onClose, onDismissStart });
  dismissRef.current = { onClose, onDismissStart };

  function dismiss() {
    if (exitRef.current) return;
    dismissRef.current.onDismissStart?.();
    const dialog = dialogRef.current;
    if (!dialog?.animate || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      dismissRef.current.onClose();
      return;
    }
    setClosing(true);
    const transform = variant === 'drawer'
      ? window.matchMedia('(max-width: 720px)').matches ? 'translateY(24px)' : 'translateX(32px)'
      : 'translateY(8px) scale(.98)';
    const exit = dialog.animate([{ opacity: 1, transform: 'none' }, { opacity: 0, transform }],
      { duration: 180, easing: 'cubic-bezier(.4, 0, 1, 1)', fill: 'forwards' });
    exitRef.current = exit;
    void exit.finished.then(() => {
      if (exitRef.current === exit) {
        setClosing(false);
        dismissRef.current.onClose();
      }
    }, () => { /* Unmounting cancels the motion, never a newer dialog. */ });
  }

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog || !open) return;
    setClosing(false);
    const previousFocus = returnFocusTo ?? document.activeElement;
    const previousOverflow = document.documentElement.style.overflow;
    document.documentElement.style.overflow = 'hidden';
    dialog.showModal();
    closeRef.current?.focus();
    return () => {
      const exit = exitRef.current;
      exitRef.current = null;
      exit?.cancel();
      dialog.close();
      document.documentElement.style.overflow = previousOverflow;
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus({ preventScroll: true });
    };
  }, [open, returnFocusTo]);

  return (
    <dialog ref={dialogRef} className={`dialog${variant === 'drawer' ? ' source-drawer' : ''}`} data-closing={closing || undefined}
      aria-labelledby={titleId} aria-describedby={variant === 'drawer' ? undefined : bodyId}
      onCancel={(event) => { event.preventDefault(); dismiss(); }}
      onKeyDown={(event) => {
        if (event.key !== 'Tab') return;
        const focusable = [...event.currentTarget.querySelectorAll<HTMLElement>(
          'button:not([disabled]), a[href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
        )].filter((element) => {
          const style = getComputedStyle(element);
          return !element.hidden && style.display !== 'none' && style.visibility !== 'hidden';
        });
        const first = focusable[0];
        const last = focusable.at(-1);
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }}
      onClick={(event) => {
        // A native backdrop click targets the dialog, but isn't inside its bounds.
        const bounds = event.currentTarget.getBoundingClientRect();
        if (event.target === event.currentTarget && (
          event.clientX < bounds.left || event.clientX > bounds.right ||
          event.clientY < bounds.top || event.clientY > bounds.bottom
        )) dismiss();
      }}>
      <div className="dialog__content" inert={closing || undefined}>
        <div className="dialog__header">
          <h2 id={titleId}>{title}</h2>
          <Button ref={closeRef} variant="quiet" className="icon-button" aria-label={closeLabel} onClick={dismiss}>
            <Icon name="close" />
          </Button>
        </div>
        <div className="dialog__body" id={bodyId} tabIndex={variant === 'drawer' ? 0 : undefined}
          role={variant === 'drawer' ? 'region' : undefined}
          aria-label={variant === 'drawer' ? 'Source details' : undefined}>{children}</div>
        {footer && <div className="dialog__footer">{footer}</div>}
      </div>
    </dialog>
  );
}
