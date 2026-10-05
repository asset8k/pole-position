import { ResponseError } from '../api/client';
import type { ConversationDetailResponse, ConversationResponse } from '../api/contracts';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function positiveId(value: unknown) { return Number.isSafeInteger(value) && Number(value) > 0; }
function date(value: unknown) { return typeof value === 'string' && Number.isFinite(Date.parse(value)); }

export function validateConversation(value: unknown, expectedId?: number): asserts value is ConversationResponse {
  if (!isRecord(value) || !positiveId(value.id) || (expectedId !== undefined && value.id !== expectedId)
      || typeof value.title !== 'string' || !value.title.trim() || value.title.length > 160
      || !date(value.created_at) || !date(value.updated_at)) throw new ResponseError(200);
}

export function validateConversationList(value: unknown): asserts value is ConversationResponse[] {
  if (!Array.isArray(value)) throw new ResponseError(200);
  const ids = new Set<number>();
  for (const item of value) {
    validateConversation(item);
    if (ids.has(item.id)) throw new ResponseError(200);
    ids.add(item.id);
  }
}

export function validateConversationDetail(value: unknown, expectedId: number): asserts value is ConversationDetailResponse {
  validateConversation(value, expectedId);
  if (!('messages' in value) || !Array.isArray(value.messages)) throw new ResponseError(200);
  const ids = new Set<number>();
  for (const message of value.messages) {
    if (!isRecord(message) || !positiveId(message.id) || ids.has(Number(message.id))
        || message.conversation_id !== expectedId || (message.role !== 'user' && message.role !== 'assistant')
        || typeof message.content !== 'string' || !Array.isArray(message.citations)
        || !date(message.created_at)) throw new ResponseError(200);
    ids.add(Number(message.id));
  }
}

export function conversationError(error: unknown, action = 'load this conversation'): string {
  if (error instanceof Error && error.name === 'ApiError' && 'status' in error
      && (error.status === 403 || error.status === 404)) return 'This conversation is no longer available or isn’t accessible to your account.';
  if (error instanceof Error && ['ApiError', 'NetworkError', 'ResponseError'].includes(error.name)) return error.message;
  return `Unable to ${action}. Please try again.`;
}
