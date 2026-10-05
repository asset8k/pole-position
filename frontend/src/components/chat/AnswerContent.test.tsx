import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { citation } from '../../test/citations';
import { AnswerContent } from './AnswerContent';

describe('safe answer formatting', () => {
  it('renders headings, emphasis, lists, quotes, and code as semantic elements', () => {
    const content = '# Tyre rules\n\nUse **two** *specifications*.\n\n- Dry tyres\n- Wet tyres\n\n1. First\n2. Second\n\n> Consult the regulations.\n\n`B6.3.6`\n\n```text\n[S1] is code, not a citation\n```';
    const { container } = render(<AnswerContent content={content} citations={[]} onOpenSource={vi.fn()} />);
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Tyre rules');
    expect(container.querySelector('h1')).toBeNull();
    expect(container.querySelector('strong')).toHaveTextContent('two');
    expect(container.querySelector('em')).toHaveTextContent('specifications');
    expect(container.querySelectorAll('li')).toHaveLength(4);
    expect(container.querySelector('blockquote')).toHaveTextContent('Consult the regulations.');
    expect(container.querySelector('pre code')).toHaveTextContent('[S1] is code, not a citation');
    expect(screen.getByRole('region', { name: 'Answer code block' })).toHaveAttribute('tabindex', '0');
  });

  it('renders tables inside a keyboard-scrollable region', () => {
    render(<AnswerContent content={'| Axis | Direction |\n| --- | --- |\n| X | Rearwards |'} citations={[]} onOpenSource={vi.fn()} />);
    expect(screen.getByRole('region', { name: 'Answer table' })).toHaveAttribute('tabindex', '0');
    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Axis' })).toBeInTheDocument();
    expect(screen.getByRole('cell', { name: 'Rearwards' })).toBeInTheDocument();
  });

  it.each([
    '<script>window.hacked=true</script>',
    '<img src="https://evil.test/x" onerror="alert(1)">',
    '<iframe src="https://evil.test"></iframe>',
    '<svg onload="alert(1)"><a href="javascript:alert(1)">x</a></svg>',
    '<style>body { display:none }</style>',
    '<button onclick="alert(1)">Fake source</button>',
  ])('keeps raw HTML inert: %s', (content) => {
    const { container } = render(<AnswerContent content={content} citations={[]} onOpenSource={vi.fn()} />);
    expect(container.querySelector('script, img, iframe, svg, style, button, a')).toBeNull();
    expect(container.textContent).toContain(content);
  });

  it('does not navigate generated URLs or load Markdown images', () => {
    const { container } = render(<AnswerContent
      content={'[Danger](javascript:alert%281%29) [External](https://evil.test) <https://evil.test> ![Image alt](https://evil.test/pixel.png)'}
      citations={[]} onOpenSource={vi.fn()} />);
    expect(container.querySelector('a, img')).toBeNull();
    expect(container).toHaveTextContent('Danger External https://evil.test Image alt');
  });
});

describe('message-scoped citations', () => {
  it('opens the exact source from inline markers and compact source chips', async () => {
    const first = citation();
    const second = citation({ source_id: 'S2', clause_identifier: 'B6.1.2', start_pdf_page: 55, end_pdf_page: 56 });
    const open = vi.fn();
    render(<AnswerContent content={'Use **two specifications [S1]**. The mandatory tyre rule applies. [S2] [S1]'}
      citations={[first, second]} onOpenSource={open} />);
    const inline = screen.getAllByRole('button', { name: 'View source S1: B6.3.6' })[0];
    expect(inline).toHaveAttribute('aria-haspopup', 'dialog');
    expect(inline).toHaveAttribute('title', 'Sporting Regulations · PDF page 58');
    await userEvent.setup().click(inline);
    expect(open).toHaveBeenLastCalledWith(first, inline);
    const chip = within(screen.getByRole('group', { name: 'Sources' }))
      .getByRole('button', { name: 'View source S2: B6.1.2' });
    expect(chip).toHaveAttribute('title', 'Sporting Regulations · PDF pages 55–56');
    await userEvent.setup().click(chip);
    expect(open).toHaveBeenLastCalledWith(second, chip);
    expect(within(screen.getByRole('group', { name: 'Sources' })).getAllByRole('button')).toHaveLength(2);
  });

  it('leaves missing markers as text without fabricating a clickable source', () => {
    render(<AnswerContent content="Unknown [S99] and malformed [S01]." citations={[citation()]} onOpenSource={vi.fn()} />);
    expect(screen.getByText('Unknown [S99] and malformed [S01].')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /S99|S01/ })).not.toBeInTheDocument();
  });

  it('renders empty-citation answers without a source row or buttons', () => {
    render(<AnswerContent content="Not enough evidence. [S1]" citations={[]} onOpenSource={vi.fn()} />);
    expect(screen.getByText('Not enough evidence. [S1]')).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'Sources' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('does not turn markers in code, links, or image alt text into citations', () => {
    const { container } = render(<AnswerContent content={'`[S1]`\n\n```\n[S1]\n```\n\n[[S1]](https://example.test) ![[S1]](https://example.test/img)'}
      citations={[citation()]} onOpenSource={vi.fn()} />);
    expect(container.querySelector('.answer-content')?.querySelector('button')).toBeNull();
    expect(screen.getByRole('group', { name: 'Sources' }).querySelectorAll('button')).toHaveLength(1);
  });

  it('rejects ambiguous duplicate IDs instead of choosing an arbitrary source', () => {
    render(<AnswerContent content="Answer [S1]" citations={[citation(), citation({ snippet: 'Different source' })]} onOpenSource={vi.fn()} />);
    expect(screen.getByText('Answer [S1]')).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});
