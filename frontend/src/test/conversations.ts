import type { ConversationDetailResponse, ConversationResponse } from '../api/contracts';
import { citation } from './citations';

export function conversation(id = 1, title = 'Tyre requirements'): ConversationResponse {
  return { id, title, created_at: '2026-10-04T12:00:00Z', updated_at: '2026-10-05T12:00:00Z' };
}
export function conversationDetail(id = 1, title = 'Tyre requirements'): ConversationDetailResponse {
  return { ...conversation(id, title), messages: [
    { id: id * 100 + 1, conversation_id: id, role: 'user', content: `${title}?`, citations: [], created_at: '2026-10-04T12:00:00Z' },
    { id: id * 100 + 2, conversation_id: id, role: 'assistant', content: `Saved answer for ${title}. [S1]`, citations: [citation()], created_at: '2026-10-04T12:00:00Z' },
  ] };
}
