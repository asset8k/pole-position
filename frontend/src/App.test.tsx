import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { App } from './App';

describe('foundation preview', () => {
  it('mounts the brand, materials, and clearly identifies the preview', () => {
    render(<App />);
    expect(screen.getByLabelText('Pole Position')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Clarity.At speed.');
    expect(screen.getByText('Design preview')).toBeInTheDocument();
    expect(screen.getAllByRole('heading', { level: 2 })).toHaveLength(3);
  });

  it('enables preview for nonblank input and resets the local state', async () => {
    const user = userEvent.setup();
    render(<App />);
    const input = screen.getByRole('textbox', { name: 'Question preview' });
    const preview = screen.getByRole('button', { name: 'Preview' });
    expect(preview).toBeDisabled();
    await user.type(input, '   ');
    expect(preview).toBeDisabled();
    await user.type(input, 'What is the tyre rule?');
    await user.click(preview);
    expect(screen.getByRole('status')).toHaveTextContent('Controls ready. Chat comes next.');
    await user.click(screen.getByRole('button', { name: 'Reset' }));
    expect(input).toHaveValue('');
    expect(preview).toBeDisabled();
  });
});
