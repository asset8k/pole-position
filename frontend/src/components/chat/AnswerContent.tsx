import { createContext, useContext, useMemo } from 'react';
import type { ComponentPropsWithoutRef } from 'react';
import Markdown from 'react-markdown';
import type { Components, ExtraProps } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Citation } from '../../api/contracts';
import { pageLabel, sourceLabel, usableCitations } from './citationUtils';
import { remarkCitations } from './remarkCitations';

interface AnswerContentProps {
  content: string;
  citations: Citation[];
  onOpenSource: (source: Citation, trigger: HTMLButtonElement) => void;
}

const allowedElements = ['p', 'strong', 'em', 'del', 'blockquote', 'ul', 'ol', 'li', 'pre', 'code',
  'hr', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'table', 'thead', 'tbody', 'tr', 'th', 'td',
  'a', 'img', 'input', 'sup', 'section', 'cite'];

const SourceContext = createContext<{
  byId: ReadonlyMap<string, Citation>; onOpen: AnswerContentProps['onOpenSource'];
} | null>(null);

function CitationButton({ source, onOpen, chip = false }: {
  source: Citation; onOpen: AnswerContentProps['onOpenSource']; chip?: boolean;
}) {
  return <button type="button" className={chip ? 'source-chip' : 'citation-button'}
    aria-label={`View source ${source.source_id}: ${sourceLabel(source)}`}
    aria-haspopup="dialog" title={`${source.document_title} · ${pageLabel(source)}`}
    onClick={(event) => onOpen(source, event.currentTarget)}>
    {chip ? <><span>{source.source_id}</span><span>{sourceLabel(source)}</span></> : source.source_id}
  </button>;
}

function InlineCitation({ node, children }: ComponentPropsWithoutRef<'cite'> & ExtraProps) {
  const context = useContext(SourceContext);
  const id = node?.properties['data-source-id'];
  const source = typeof id === 'string' ? context?.byId.get(id) : undefined;
  return source && context ? <CitationButton source={source} onOpen={context.onOpen} /> : <>{children}</>;
}

// Stable component identities keep the clicked citation in the DOM when its
// drawer opens, so closing can return focus to the exact originating button.
const markdownComponents: Components = {
  a: ({ children }) => <>{children}</>,
  img: ({ alt }) => <span>{alt}</span>,
  input: ({ checked }) => <input type="checkbox" checked={Boolean(checked)} disabled aria-label="Answer checklist item" />,
  h1: ({ children }) => <h2>{children}</h2>, h2: ({ children }) => <h2>{children}</h2>,
  h3: ({ children }) => <h2>{children}</h2>, h4: ({ children }) => <h2>{children}</h2>,
  h5: ({ children }) => <h2>{children}</h2>, h6: ({ children }) => <h2>{children}</h2>,
  pre: ({ children }) => <pre role="region" aria-label="Answer code block" tabIndex={0}>{children}</pre>,
  table: ({ children }) => <div className="answer-table" role="region" aria-label="Answer table" tabIndex={0}><table>{children}</table></div>,
  cite: InlineCitation,
};

export function AnswerContent({ content, citations, onOpenSource }: AnswerContentProps) {
  const sources = useMemo(() => usableCitations(citations), [citations]);
  const byId = useMemo(() => new Map(sources.map((source) => [source.source_id, source])), [sources]);
  const citationPlugin = useMemo(() => remarkCitations(new Set(byId.keys())), [byId]);

  return <SourceContext.Provider value={{ byId, onOpen: onOpenSource }}>
    <div className="answer-content">
      <Markdown remarkPlugins={[remarkGfm, citationPlugin]} allowedElements={allowedElements}
        // No raw-HTML plugin. Raw HTML remains escaped text. Generated links and
        // images are inert: only API-backed citation controls are navigable.
        urlTransform={() => ''} components={markdownComponents}>{content}</Markdown>
    </div>
    {sources.length > 0 && <div className="answer-sources" role="group" aria-label="Sources">
      <span className="answer-sources__label">Sources</span>
      {sources.map((source) => <CitationButton key={source.source_id} source={source} onOpen={onOpenSource} chip />)}
    </div>}
  </SourceContext.Provider>;
}
