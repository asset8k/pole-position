import { useRef, useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { Composer } from './Composer';

function Harness({ onSubmit }: { onSubmit: (question: string) => void }) {
  const [value, setValue] = useState('');
  const inputRef = useRef<HTMLTextAreaElement>(null);
  return <Composer value={value} inputRef={inputRef} onChange={setValue} onSubmit={onSubmit} />;
}

describe('Composer', () => {
  it('blocks button, Enter, and form submissions while pending', () => {
    const submit = vi.fn();
    render(<Composer value="Question" inputRef={{ current: null }} onChange={vi.fn()} onSubmit={submit} pending />);
    expect(screen.getByRole('textbox')).toHaveAttribute('readonly');
    expect(screen.getByRole('button', { name: 'Send question' })).toBeDisabled();
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
    fireEvent.submit(screen.getByRole('form'));
    expect(submit).not.toHaveBeenCalled();
  });

  it('trims the question before submission', async () => {
    const user = userEvent.setup();
    const submit = vi.fn();
    render(<Harness onSubmit={submit} />);
    await user.type(screen.getByRole('textbox'), '  A regulation question  ');
    await user.click(screen.getByRole('button', { name: 'Send question' }));
    expect(submit).toHaveBeenCalledExactlyOnceWith('A regulation question');
    expect(screen.getByRole('textbox')).toHaveAttribute('maxlength', '4000');
  });

  it('Shift+Enter adds a line, while Enter submits without adding a line', async () => {
    const user = userEvent.setup();
    const submit = vi.fn();
    render(<Harness onSubmit={submit} />);
    const input = screen.getByRole('textbox');
    await user.type(input, 'First line');
    await user.keyboard('{Shift>}{Enter}{/Shift}Second line');
    expect(input).toHaveValue('First line\nSecond line');
    expect(submit).not.toHaveBeenCalled();
    await user.keyboard('{Enter}');
    expect(submit).toHaveBeenCalledExactlyOnceWith('First line\nSecond line');
    expect(input).toHaveValue('First line\nSecond line');
  });

  it('does not submit blank text or Enter during IME composition', async () => {
    const user = userEvent.setup();
    const submit = vi.fn();
    render(<Harness onSubmit={submit} />);
    const input = screen.getByRole('textbox');
    await user.type(input, '   {Enter}');
    expect(submit).not.toHaveBeenCalled();
    await user.type(input, '日本語');
    fireEvent.keyDown(input, { key: 'Enter', isComposing: true });
    fireEvent.keyDown(input, { key: 'Enter', keyCode: 229 });
    expect(submit).not.toHaveBeenCalled();
  });
});
