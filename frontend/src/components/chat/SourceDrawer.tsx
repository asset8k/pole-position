import type { Citation } from '../../api/contracts';
import { Dialog } from '../ui/Dialog';
import { pageLabel, sourceLabel } from './citationUtils';
import { Icon } from '../ui/Icon';

// Link to FIA's live catalogue, not a hard-coded PDF that can become outdated.
const FIA_REGULATIONS_URL = 'https://www.fia.com/regulation/category/110';

export interface SelectedSource {
  messageId: number;
  source: Citation;
  trigger: HTMLButtonElement;
}

export function SourceDrawer({ selection, onClose }: { selection: SelectedSource; onClose: () => void }) {
  const { source, trigger } = selection;
  return <Dialog open variant="drawer" title={`Source ${source.source_id}`} closeLabel="Close source"
    returnFocusTo={trigger} onClose={onClose} footer={<>
      <a className="source-official-link" href={FIA_REGULATIONS_URL} target="_blank" rel="noopener noreferrer">
        <span><span className="source-official-link__label">Official FIA library</span>
          <span className="source-official-link__title">Full regulations</span></span>
        <Icon name="arrow-out" />
        <span className="sr-only"> (opens in a new tab)</span>
      </a>
      <p className="source-official-note">FIA’s latest editions may differ from this excerpt.</p>
    </>}>
    <div className="source-document">
      <span className="source-document__edition">2026 FIA regulations</span>
      <h3>{source.document_title}</h3>
      <dl className="source-metadata">
        <div><dt>Section</dt><dd>{source.section}</dd></div>
        <div><dt>Reference</dt><dd>{sourceLabel(source)}</dd></div>
        <div><dt>Location</dt><dd>{pageLabel(source)}</dd></div>
      </dl>
    </div>
    <section className="source-excerpt" aria-label="Retrieved excerpt">
      <span className="source-excerpt__label">Retrieved excerpt</span>
      <p>{source.snippet}</p>
    </section>
    <p className="source-drawer__note">This is the retrieved passage, not the entire PDF.</p>
  </Dialog>;
}
