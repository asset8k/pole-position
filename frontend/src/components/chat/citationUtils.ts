import type { Citation } from '../../api/contracts';

function text(value: unknown): value is string {
  return typeof value === 'string' && Boolean(value.trim());
}

function isCitation(value: unknown): value is Citation {
  if (typeof value !== 'object' || value === null) return false;
  const source = value as Partial<Citation>;
  if (!text(source.source_id) || !/^S[1-9]\d*$/.test(source.source_id)
      || !text(source.chunk_id) || !text(source.document_id)
      || !text(source.document_title) || !text(source.snippet)
      || typeof source.section !== 'string' || !/^[A-F]$/.test(source.section)
      || !Number.isSafeInteger(source.start_pdf_page) || !Number.isSafeInteger(source.end_pdf_page)
      || source.start_pdf_page! < 1 || source.end_pdf_page! < source.start_pdf_page!) return false;
  if (source.source_kind === 'clause') {
    return text(source.article_identifier) && text(source.clause_identifier)
      && source.clause_identifier.startsWith(`${source.article_identifier}.`)
      && source.article_identifier.startsWith(source.section) && source.appendix_identifier === null;
  }
  if (source.source_kind === 'appendix') {
    return text(source.appendix_identifier) && source.appendix_identifier.startsWith(source.section)
      && source.article_identifier === null && source.clause_identifier === null;
  }
  return source.source_kind === 'preamble' && source.article_identifier === null
    && source.clause_identifier === null && source.appendix_identifier === null;
}

export function usableCitations(value: unknown): Citation[] {
  if (!Array.isArray(value)) return [];
  const counts = new Map<string, number>();
  for (const entry of value) {
    if (entry && typeof entry.source_id === 'string') {
      counts.set(entry.source_id, (counts.get(entry.source_id) ?? 0) + 1);
    }
  }
  // Ambiguous/invalid sources never become clickable. IDs are local to one answer.
  return value.filter(isCitation).filter((source) => counts.get(source.source_id) === 1);
}

export function sourceLabel(source: Citation): string {
  if (source.source_kind === 'clause') return source.clause_identifier!;
  if (source.source_kind === 'appendix') return `Appendix ${source.appendix_identifier}`;
  return 'Preamble';
}

export function pageLabel(source: Citation): string {
  return source.start_pdf_page === source.end_pdf_page
    ? `PDF page ${source.start_pdf_page}`
    : `PDF pages ${source.start_pdf_page}\u2013${source.end_pdf_page}`;
}
