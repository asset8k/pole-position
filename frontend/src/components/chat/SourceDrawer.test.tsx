import { useRef } from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { citation } from '../../test/citations';
import { ChatScreen } from './ChatScreen';

function Harness({ extra = false }: { extra?: boolean }) {
  const composerRef = useRef<HTMLTextAreaElement>(null);
  return <ChatScreen draft="" activeTurn={null} composerRef={composerRef} onChange={vi.fn()} onSubmit={vi.fn()}
    messages={[
      { id: 2, role: 'assistant', content: 'Tyre answer [S1]', citations: [citation()] },
      { id: 4, role: 'assistant', content: 'Cost cap answer [S1]', citations: [citation({
        section: 'D', article_identifier: 'D1', clause_identifier: 'D1.2.1',
        document_title: 'Financial Regulations (F1 Teams)', start_pdf_page: 4, end_pdf_page: 5,
        snippet: 'D1.2.1 Full retrieved financial excerpt.\n<script>Never execute this.</script>',
      })] },
      ...(extra ? [{ id: 6, role: 'assistant' as const, content: 'A newer answer [S1]', citations: [citation({
        clause_identifier: 'B6.1.2', snippet: 'Newer source excerpt.',
      })] }] : []),
    ]} />;
}

describe('source drawer', () => {
  it('resolves repeated S1 markers to their own answer and restores exact trigger focus', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const first = screen.getAllByRole('button', { name: 'View source S1: B6.3.6' })[0];
    await user.click(first);
    let drawer = screen.getByRole('dialog', { name: 'Source S1' });
    expect(within(drawer).getByText('Sporting Regulations')).toBeInTheDocument();
    expect(within(drawer).getByText('PDF page 58')).toBeInTheDocument();
    expect(within(drawer).getByRole('region', { name: 'Retrieved excerpt' })).toHaveTextContent(citation().snippet.replace(/\n/g, ' '));
    expect(screen.getByRole('button', { name: 'Close source' })).toHaveFocus();
    expect(first.isConnected).toBe(true);
    expect(document.documentElement.style.overflow).toBe('hidden');
    await user.tab();
    expect(screen.getByRole('region', { name: 'Source details' })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole('button', { name: 'Close source' })).toHaveFocus();
    await user.tab({ shift: true });
    expect(screen.getByRole('region', { name: 'Source details' })).toHaveFocus();
    await user.click(screen.getByRole('button', { name: 'Close source' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(first).toHaveFocus();
    expect(document.documentElement.style.overflow).toBe('');

    const second = screen.getAllByRole('button', { name: 'View source S1: D1.2.1' })[0];
    await user.click(second);
    drawer = screen.getByRole('dialog', { name: 'Source S1' });
    expect(within(drawer).getByText('Financial Regulations (F1 Teams)')).toBeInTheDocument();
    expect(within(drawer).getByText('PDF pages 4–5')).toBeInTheDocument();
    expect(within(drawer).getByRole('region', { name: 'Retrieved excerpt' })).toHaveTextContent('<script>Never execute this.</script>');
    expect(drawer.querySelector('script')).toBeNull();
    fireEvent(drawer, new Event('cancel', { cancelable: true, bubbles: true }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(second).toHaveFocus();
  });

  it('restores the previous scroll-lock value when unmounted with a source open', async () => {
    document.documentElement.style.overflow = 'clip';
    try {
      const { unmount } = render(<Harness />);
      await userEvent.setup().click(screen.getAllByRole('button', { name: 'View source S1: B6.3.6' })[0]);
      unmount();
      expect(document.documentElement.style.overflow).toBe('clip');
    } finally { document.documentElement.style.overflow = ''; }
  });

  it('keeps the open source and trigger stable when another answer arrives', async () => {
    const user = userEvent.setup();
    const { rerender } = render(<Harness />);
    const trigger = screen.getAllByRole('button', { name: 'View source S1: B6.3.6' })[0];
    await user.click(trigger);
    rerender(<Harness extra />);
    expect(screen.getByRole('button', { name: 'Close source' })).toHaveFocus();
    expect(screen.getByRole('dialog').querySelector('.source-excerpt p')?.textContent).toBe(citation().snippet);
    expect(trigger.isConnected).toBe(true);
    await user.click(screen.getByRole('button', { name: 'Close source' }));
    expect(trigger).toHaveFocus();
  });
});
