import { describe, expect, it } from 'vitest';
import { conversation, conversationDetail } from '../test/conversations';
import { validateConversation, validateConversationDetail, validateConversationList } from './conversationValidation';

describe('saved conversation response validation', () => {
  it('accepts lists, empty conversations, and the backend message/citation shape', () => {
    expect(() => validateConversationList([])).not.toThrow();
    expect(() => validateConversationList([conversation(1), conversation(2)])).not.toThrow();
    expect(() => validateConversationDetail(conversationDetail(), 1)).not.toThrow();
    expect(() => validateConversationDetail({ ...conversation(), messages: [] }, 1)).not.toThrow();
  });
  it.each([null, {}, { ...conversation(), id: -1 }, { ...conversation(), title: '' },
    { ...conversation(), title: 'a'.repeat(161) }, { ...conversation(), updated_at: 'invalid' },
  ])('rejects malformed conversation metadata %#', (value) => {
    expect(() => validateConversation(value)).toThrow();
  });
  it('rejects duplicate list IDs and a detail belonging to a different requested ID', () => {
    expect(() => validateConversationList([conversation(), conversation()])).toThrow();
    expect(() => validateConversationDetail(conversationDetail(2), 1)).toThrow();
  });
  it.each([
    { role: 'system' }, { content: null }, { citations: null }, { created_at: 'invalid' }, { conversation_id: 2 }, { id: 0 },
  ])('rejects malformed or cross-conversation messages %#', (overrides) => {
    const detail = conversationDetail();
    expect(() => validateConversationDetail({ ...detail, messages: [{ ...detail.messages[0], ...overrides }] }, 1)).toThrow();
  });
  it('rejects duplicate message IDs instead of allowing citation collisions', () => {
    const detail = conversationDetail();
    expect(() => validateConversationDetail({ ...detail, messages: [detail.messages[0], detail.messages[0]] }, 1)).toThrow();
  });
});
