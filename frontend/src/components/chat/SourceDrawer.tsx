import type { Citation } from '../../api/contracts';
import { Dialog } from '../ui/Dialog';
import { pageLabel, sourceLabel } from './citationUtils';

export interface SelectedSource {
  messageId: number;
  source: Citation;
  trigger: HTMLButtonElement;
}

export function SourceDrawer({ selection, onClose }: { selection: SelectedSource; onClose: () => void }) {
  const { source, trigger } = selection;
  return <Dialog open variant="drawer" title={`Source ${source.source_id}`} closeLabel="Close source"
    returnFocusTo={trigger} onClose={onClose}>
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
