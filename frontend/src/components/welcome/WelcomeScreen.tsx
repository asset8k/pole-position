import type { RefObject } from 'react';
import { Icon } from '../ui/Icon';
import { Composer } from './Composer';
import { suggestions } from './suggestions';

type WelcomeScreenProps = {
  question: string;
  composerRef: RefObject<HTMLTextAreaElement | null>;
  onChange: (value: string) => void;
  onSuggestion: (value: string) => void;
  onSubmit: (question: string) => void;
  authenticated?: boolean;
};

export function WelcomeScreen({ question, composerRef, onChange, onSuggestion, onSubmit, authenticated = false }: WelcomeScreenProps) {
  return (
    <section className="welcome" aria-labelledby="welcome-title">
      <div className="welcome__intro">
        <span className="edition"><span aria-hidden="true" />2026 F1 regulations</span>
        <h1 id="welcome-title">Know the <span>rules.</span></h1>
        <p>Clear answers. Original sources.</p>
      </div>
      <div className="welcome__workspace">
        <Composer value={question} inputRef={composerRef} onChange={onChange} onSubmit={onSubmit} />
        <ul className="suggestions" aria-label="Suggested questions">
          {suggestions.map((suggestion) => (
            <li key={suggestion.label}>
              <button className="suggestion" type="button" title={suggestion.question}
                aria-describedby={`suggestion-${suggestion.icon}`} onClick={() => onSuggestion(suggestion.question)}>
                <Icon name={suggestion.icon} /><span>{suggestion.label}</span><Icon name="arrow-out" className="suggestion__arrow" />
              </button>
              <span className="sr-only" id={`suggestion-${suggestion.icon}`}>{suggestion.question}</span>
            </li>
          ))}
        </ul>
        <p className="welcome__status" role="status">
          {authenticated ? 'Conversations save to your account' : <>Guest chat <span aria-hidden="true">·</span> Clears on refresh</>}
        </p>
      </div>
    </section>
  );
}
