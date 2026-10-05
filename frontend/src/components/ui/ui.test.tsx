import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { Button } from './Button';
import { GlassSurface } from './GlassSurface';
import { Input } from './Input';

describe('Button', () => {
  it('defaults to button, supports variants, and calls its handler', async () => {
    const onClick = vi.fn();
    render(<Button variant="glass" onClick={onClick}>Continue</Button>);
    const button = screen.getByRole('button', { name: 'Continue' });
    expect(button).toHaveAttribute('type', 'button');
    expect(button).toHaveClass('button--glass');
    await userEvent.click(button);
    expect(onClick).toHaveBeenCalledOnce();
  });

  it.each([{ disabled: true }, { loading: true }])('blocks interaction in %j state', async (state) => {
    const onClick = vi.fn();
    render(<Button {...state} onClick={onClick}>Continue</Button>);
    const button = screen.getByRole('button', { name: 'Continue' });
    expect(button).toBeDisabled();
    await userEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
    if ('loading' in state) expect(button).toHaveAttribute('aria-busy', 'true');
  });
});

describe('Input', () => {
  it('associates label and hint, accepts text, and allows keyboard focus', async () => {
    const user = userEvent.setup();
    render(<Input label="Username" hint="Lowercase only" />);
    const input = screen.getByRole('textbox', { name: 'Username' });
    expect(input).toHaveAccessibleDescription('Lowercase only');
    await user.tab();
    expect(input).toHaveFocus();
    await user.type(input, 'assetk');
    expect(input).toHaveValue('assetk');
  });

  it('exposes an error and preserves caller-provided descriptions', () => {
    render(<><span id="existing">Required</span><Input label="Username" error="Too short"
      hint="Not shown" aria-describedby="existing" /></>);
    const input = screen.getByRole('textbox', { name: 'Username' });
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(input).toHaveAccessibleDescription('Required Too short');
    expect(screen.queryByText('Not shown')).not.toBeInTheDocument();
  });

  it('cannot edit or focus disabled inputs', async () => {
    const user = userEvent.setup();
    render(<Input label="Username" disabled defaultValue="assetk" />);
    const input = screen.getByRole('textbox');
    await user.type(input, 'more');
    await user.tab();
    expect(input).toHaveValue('assetk');
    expect(input).not.toHaveFocus();
  });
});

it('GlassSurface preserves attributes and applies the requested material', () => {
  render(<GlassSurface tone="reading" className="custom" aria-label="Reading surface">Text</GlassSurface>);
  expect(screen.getByLabelText('Reading surface')).toHaveClass('glass', 'glass--reading', 'custom');
});
