import { useId } from 'react';
import type { InputHTMLAttributes } from 'react';

type InputProps = InputHTMLAttributes<HTMLInputElement> & {
  label: string;
  error?: string;
  hint?: string;
};

export function Input({ label, error, hint, id, className = '', ...props }: InputProps) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const message = error || hint;
  const messageId = `${inputId}-message`;
  const describedBy = [props['aria-describedby'], message ? messageId : undefined]
    .filter(Boolean).join(' ') || undefined;

  return (
    <div className="field">
      <label className="field__label" htmlFor={inputId}>{label}</label>
      <input {...props} id={inputId} className={`input ${className}`.trim()}
        aria-invalid={error ? true : props['aria-invalid']}
        aria-describedby={describedBy} />
      {message && <p id={messageId} className={`field__message ${error ? 'field__message--error' : ''}`}>
        {message}
      </p>}
    </div>
  );
}
