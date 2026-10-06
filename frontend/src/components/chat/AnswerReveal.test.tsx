import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { citation } from '../../test/citations';
import { AnswerContent } from './AnswerContent';

beforeEach(() => vi.useFakeTimers());
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

const answer = 'Use **two different tyre specifications** during the race. [S1]\n\n' +
  'Unless intermediate or wet-weather tyres are used, this requirement applies. '.repeat(4);

describe('progressive formatted answers', () => {
  it('reveals whole words from full Markdown, then enables correct citations', () => {
    const open = vi.fn();
    const { container } = render(<AnswerContent content={answer} citations={[citation()]} onOpenSource={open} animate />);
    const content = container.querySelector('.answer-content')!;
    const initial = content.textContent!;
    expect(initial).toContain('Use two');
    expect(initial).not.toContain('**');
    expect(content.querySelector('strong')).not.toBeNull();
    expect(screen.queryByRole('group', { name: 'Sources' })).toBeNull();
    expect(container.querySelector('.answer-response')).toHaveAttribute('aria-busy', 'true');
    act(() => vi.advanceTimersByTime(400));
    expect(content.textContent!.length).toBeGreaterThan(initial.length);
    expect(content.textContent).not.toContain('**');
    expect(content.querySelector('.citation-button')).toBeDisabled();
    act(() => vi.advanceTimersByTime(3000));
    expect(container.querySelector('.answer-response')).toHaveAttribute('aria-busy', 'false');
    expect(screen.queryByRole('button', { name: 'Show full answer' })).toBeNull();
    const button = screen.getAllByRole('button', { name: /View source S1/ })[0];
    fireEvent.click(button);
    expect(open).toHaveBeenCalledWith(citation(), button);
  });

  it('allows an immediate reveal and keeps keyboard focus on the answer', () => {
    const { container } = render(<AnswerContent content={answer} citations={[]} onOpenSource={vi.fn()} animate />);
    fireEvent.click(screen.getByRole('button', { name: 'Show full answer' }));
    expect(container.querySelector('.answer-content')).toHaveFocus();
    expect(container.querySelector('.answer-content')).toHaveTextContent('wet-weather tyres');
    const completed = container.querySelector('.answer-content')!.textContent;
    act(() => vi.advanceTimersByTime(3000));
    expect(container.querySelector('.answer-content')!.textContent).toBe(completed);
  });

  it('does not replay during unrelated renders and finishes when another turn starts', () => {
    const props = { content: answer, citations: [], onOpenSource: vi.fn() };
    const view = render(<AnswerContent {...props} animate />);
    act(() => vi.advanceTimersByTime(500));
    const before = view.container.querySelector('.answer-content')!.textContent;
    view.rerender(<AnswerContent {...props} onOpenSource={vi.fn()} animate />);
    expect(view.container.querySelector('.answer-content')!.textContent).toBe(before);
    view.rerender(<AnswerContent {...props} animate={false} />);
    expect(view.container.querySelector('.answer-content')).toHaveTextContent('wet-weather tyres');
    expect(vi.getTimerCount()).toBe(0);
  });

  it('reveals Unicode words, code and raw HTML atomically without executing HTML', () => {
    const content = 'Rules 👩🏽‍🔧 apply.\n\n```text\n**not emphasis**\n```\n\n<img src="x" onerror="alert(1)">';
    const view = render(<AnswerContent content={content} citations={[]} onOpenSource={vi.fn()} animate />);
    expect(view.container).toHaveTextContent('👩🏽‍🔧');
    expect(view.container.querySelector('pre')).toBeNull();
    act(() => vi.advanceTimersByTime(3000));
    expect(view.container.querySelector('pre code')).toHaveTextContent('**not emphasis**');
    expect(view.container.querySelector('img')).toBeNull();
    expect(view.container).toHaveTextContent('<img src="x" onerror="alert(1)">');
  });
});
