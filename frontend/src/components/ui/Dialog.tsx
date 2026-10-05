import { useEffect, useId, useRef } from 'react';
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
};

export function Dialog({ open, title, children, onClose, returnFocusTo, variant = 'dialog', closeLabel = 'Close dialog' }: DialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const bodyId = useId();

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog || !open) return;
    const previousFocus = returnFocusTo ?? document.activeElement;
    const previousOverflow = document.documentElement.style.overflow;
    document.documentElement.style.overflow = 'hidden';
    dialog.showModal();
    closeRef.current?.focus();
    return () => {
      dialog.close();
      document.documentElement.style.overflow = previousOverflow;
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus();
    };
  }, [open, returnFocusTo]);

  return (
    <dialog ref={dialogRef} className={`dialog${variant === 'drawer' ? ' source-drawer' : ''}`}
      aria-labelledby={titleId} aria-describedby={variant === 'drawer' ? undefined : bodyId}
      onCancel={(event) => { event.preventDefault(); onClose(); }}
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
        )) onClose();
      }}>
      <div className="dialog__content">
        <div className="dialog__header">
          <h2 id={titleId}>{title}</h2>
          <Button ref={closeRef} variant="quiet" className="icon-button" aria-label={closeLabel} onClick={onClose}>
            <Icon name="close" />
          </Button>
        </div>
        <div className="dialog__body" id={bodyId} tabIndex={variant === 'drawer' ? 0 : undefined}
          role={variant === 'drawer' ? 'region' : undefined}
          aria-label={variant === 'drawer' ? 'Source details' : undefined}>{children}</div>
      </div>
    </dialog>
  );
}
