import { useRef, useState } from 'react';
import type { ConversationAction } from './ConversationList';
import type { SavedConversations } from '../../chat/useSavedConversations';
import { conversationError } from '../../chat/conversationValidation';
import { Dialog } from '../ui/Dialog';
import { Button } from '../ui/Button';
import { Input } from '../ui/Input';

export function ConversationActionDialog({ action, saved, onClose, onDeleted }: {
  action: ConversationAction; saved: SavedConversations; onClose: () => void; onDeleted: (id: number) => void;
}) {
  const [title, setTitle] = useState(action.item.title);
  const [error, setError] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const lock = useRef(false);
  const rename = action.kind === 'rename';
  const busy = saved.mutation !== null;
  const invalid = !title.trim() || title.trim().length > 160;

  function close() { if (!lock.current) onClose(); }
  async function submit() {
    if (lock.current) return;
    setSubmitted(true); setError('');
    if (rename && invalid) return;
    lock.current = true;
    try {
      const result = rename ? await saved.rename(action.item, title) : await saved.delete(action.item);
      if (!result) return;
      if (!rename) onDeleted(action.item.id);
      onClose();
    } catch (cause) {
      setError(conversationError(cause, rename ? 'rename this conversation' : 'delete this conversation'));
    } finally { lock.current = false; }
  }
  return <Dialog open title={rename ? 'Rename conversation' : 'Delete conversation?'}
    closeLabel="Close conversation action" returnFocusTo={action.trigger} onClose={close}>
    <form className="conversation-action" onSubmit={(event) => { event.preventDefault(); void submit(); }} noValidate aria-busy={busy}>
      {rename ? <Input label="Conversation title" value={title} maxLength={160} readOnly={busy}
        error={submitted && invalid ? 'Use a title between 1 and 160 characters.' : undefined}
        onChange={(event) => { setTitle(event.target.value); setError(''); }} />
        : <><p className="conversation-action__title">{action.item.title}</p>
          <p>This removes the conversation and its messages. It can’t be undone.</p></>}
      {error && <p className="conversation-action__error" role="alert">{error}</p>}
      <div className="conversation-action__buttons">
        <Button variant="quiet" disabled={busy} onClick={close}>Cancel</Button>
        <Button type="submit" loading={busy}>{rename ? 'Save title' : 'Delete conversation'}</Button>
      </div>
    </form>
  </Dialog>;
}
