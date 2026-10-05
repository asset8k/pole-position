import type { ButtonHTMLAttributes } from 'react';

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'glass' | 'quiet';
  loading?: boolean;
};

export function Button({
  variant = 'primary', loading = false, disabled = false,
  className = '', children, type = 'button', ...props
}: ButtonProps) {
  return (
    <button {...props} type={type} disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={`button button--${variant} ${className}`.trim()}>
      {loading && <span className="spinner" aria-hidden="true" />}
      {children}
    </button>
  );
}
