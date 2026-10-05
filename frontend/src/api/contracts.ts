// JSON contracts for the existing FastAPI endpoints. Dates remain ISO strings.
export type RegulationSection = 'A' | 'B' | 'C' | 'D' | 'E' | 'F';
export type SourceKind = 'clause' | 'appendix' | 'preamble';
export type MessageRole = 'user' | 'assistant';

export interface ChatHistoryMessage {
  role: MessageRole;
  content: string;
}

export interface ChatRequest {
  message: string;
  conversation_id?: number | null;
  history?: ChatHistoryMessage[];
}

export interface Citation {
  source_id: string;
  chunk_id: string;
  document_id: string;
  document_title: string;
  section: RegulationSection;
  source_kind: SourceKind;
  article_identifier: string | null;
  clause_identifier: string | null;
  appendix_identifier: string | null;
  start_pdf_page: number;
  end_pdf_page: number;
  snippet: string;
}

export interface ChatResponse {
  answer: string;
  citations: Citation[];
  conversation_id: number | null;
}

export interface MessageResponse {
  id: number;
  conversation_id: number;
  role: MessageRole;
  content: string;
  citations: Citation[];
  created_at: string;
}

export interface ConversationResponse {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ConversationDetailResponse extends ConversationResponse {
  messages: MessageResponse[];
}

export interface ConversationUpdateRequest {
  title: string;
}

export interface RegisterRequest {
  username: string;
  password: string;
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface UserResponse {
  id: number;
  username: string;
  created_at: string;
}
