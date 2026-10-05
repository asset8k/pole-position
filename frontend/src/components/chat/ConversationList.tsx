import type { ConversationResponse } from '../../api/contracts';
import type { SavedConversations } from '../../chat/useSavedConversations';
import { Button } from '../ui/Button';
import { Icon } from '../ui/Icon';

export type ConversationAction = { kind: 'rename' | 'delete'; item: ConversationResponse; trigger: HTMLElement };

export function ConversationList({ saved, selectedId, onOpen, onNewChat, onManage }: {
  saved: SavedConversations; selectedId: number | null;
  onOpen: (id: number) => void; onNewChat: () => void;
  onManage: (action: ConversationAction) => void;
}) {
  return <div className="conversation-list">
    <div className="conversation-list__header">
      <span>YOUR CHATS</span>
      <Button variant="quiet" className="icon-button" aria-label="Refresh saved chats" loading={saved.loading}
        onClick={() => { void saved.reload(); }}><Icon name="refresh" /></Button>
    </div>
    <Button variant="glass" className="conversation-list__new" onClick={onNewChat}><Icon name="plus" />New conversation</Button>
    {saved.loading && <p className="conversation-list__notice" role="status">Loading saved chats…</p>}
    {saved.error && <div className="conversation-list__error" role="alert"><p>{saved.error}</p>
      <Button variant="quiet" onClick={() => { void saved.reload(); }}>Retry list</Button></div>}
    {!saved.loading && !saved.error && saved.items.length === 0 && <p className="conversation-list__empty">Your next conversation starts here.</p>}
    <nav aria-label="Saved conversations">
      <ul className="conversation-list__items">
        {saved.items.map((item) => <li key={item.id} className={`conversation-row${item.id === selectedId ? ' conversation-row--selected' : ''}`}>
          <button className="conversation-row__open" type="button" title={item.title}
            aria-label={`Open conversation: ${item.title}`} aria-current={item.id === selectedId ? 'page' : undefined}
            onClick={() => onOpen(item.id)}>
            <span>{item.title}</span>
            <time dateTime={item.updated_at}>{new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(new Date(item.updated_at))}</time>
          </button>
          <div className="conversation-row__actions">
            <Button variant="quiet" className="icon-button" aria-label={`Rename conversation: ${item.title}`}
              disabled={saved.mutation !== null} onClick={(event) => onManage({ kind: 'rename', item, trigger: event.currentTarget })}><Icon name="edit" /></Button>
            <Button variant="quiet" className="icon-button" aria-label={`Delete conversation: ${item.title}`}
              disabled={saved.mutation !== null} onClick={(event) => onManage({ kind: 'delete', item, trigger: event.currentTarget })}><Icon name="trash" /></Button>
          </div>
        </li>)}
      </ul>
    </nav>
  </div>;
}
