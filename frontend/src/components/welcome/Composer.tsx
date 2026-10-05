import { useLayoutEffect } from 'react';
import type { RefObject } from 'react';
import { Button } from '../ui/Button';
import { GlassSurface } from '../ui/GlassSurface';
import { Icon } from '../ui/Icon';

type ComposerProps = {
  value: string;
  inputRef: RefObject<HTMLTextAreaElement | null>;
  onChange: (value: string) => void;
  onSubmit: (question: string) => void;
  pending?: boolean;
};

export function Composer({ value, inputRef, onChange, onSubmit, pending = false }: ComposerProps) {
  useLayoutEffect(() => {
    const input = inputRef.current;
    if (!input) return;
    input.style.height = 'auto';
    input.style.height = `${Math.min(input.scrollHeight, 190)}px`;
  }, [value, inputRef]);

  function submit() {
    const question = value.trim();
    if (question && question.length <= 4000 && !pending) onSubmit(question);
  }

  return (
    <form className="composer-form" aria-label="Ask a regulation question" onSubmit={(event) => {
      event.preventDefault();
      submit();
    }}>
      <GlassSurface className="composer">
        <label className="sr-only" htmlFor="question">Your question</label>
        <textarea ref={inputRef} id="question" className="composer__input" rows={2} maxLength={4000}
          placeholder={pending ? 'Checking the regulations…' : 'Ask about the rules…'} value={value}
          readOnly={pending} aria-busy={pending || undefined} autoComplete="off" aria-describedby="composer-help"
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              submit();
            }
          }} />
        <div className="composer__footer">
          <span className="composer__hint" id="composer-help">{pending ? 'One moment…' : <>Enter to ask <span aria-hidden="true">·</span> Shift + Enter for a new line</>}</span>
          {value.length >= 3800 && <span className="composer__count">{value.length}/4000</span>}
          <Button type="submit" className="composer__send icon-button" aria-label="Send question"
            disabled={pending || !value.trim() || value.trim().length > 4000}><Icon name="arrow-up" /></Button>
        </div>
      </GlassSurface>
    </form>
  );
}
