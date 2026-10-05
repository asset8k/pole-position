import { describe, expect, it } from 'vitest';
import { citation } from '../../test/citations';
import { pageLabel, sourceLabel, usableCitations } from './citationUtils';

describe('source metadata', () => {
  it('labels clauses, appendices, preambles, and single/range PDF pages', () => {
    expect(sourceLabel(citation())).toBe('B6.3.6');
    expect(sourceLabel(citation({ source_kind: 'appendix', article_identifier: null, clause_identifier: null, appendix_identifier: 'B2' }))).toBe('Appendix B2');
    expect(sourceLabel(citation({ source_kind: 'preamble', article_identifier: null, clause_identifier: null }))).toBe('Preamble');
    expect(pageLabel(citation())).toBe('PDF page 58');
    expect(pageLabel(citation({ end_pdf_page: 60 }))).toBe('PDF pages 58–60');
  });

  it('accepts coherent appendix and preamble metadata', () => {
    const appendix = citation({ source_kind: 'appendix', article_identifier: null, clause_identifier: null, appendix_identifier: 'B2' });
    const preamble = citation({ source_id: 'S2', source_kind: 'preamble', article_identifier: null, clause_identifier: null });
    expect(usableCitations([appendix, preamble])).toEqual([appendix, preamble]);
  });

  it.each([null, {}, 'bad', [null], [citation({ source_id: 'S0' })], [citation({ snippet: '' })],
    [citation({ end_pdf_page: 57 })], [citation({ start_pdf_page: 0 })], [citation({ end_pdf_page: 58.5 })],
    [citation({ source_kind: 'appendix', appendix_identifier: 'B2' })],
    [citation({ source_kind: 'preamble' })], [citation({ clause_identifier: 'C2.1.1' })],
  ])('ignores unusable source data: %s', (value) => {
    expect(usableCitations(value)).toEqual([]);
  });
});
