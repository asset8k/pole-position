import type { Citation } from '../api/contracts';

export function citation(overrides: Partial<Citation> = {}): Citation {
  return {
    source_id: 'S1', chunk_id: 'fia-f1-2026-section-b-issue-08:B6.3.6:0',
    document_id: 'fia-f1-2026-section-b-issue-08', document_title: 'Sporting Regulations',
    section: 'B', source_kind: 'clause', article_identifier: 'B6', clause_identifier: 'B6.3.6',
    appendix_identifier: null, start_pdf_page: 58, end_pdf_page: 58,
    snippet: 'B6.3.6 Each driver must use at least two different dry-weather tyre specifications.\nFailure to comply results in disqualification.',
    ...overrides,
  };
}
