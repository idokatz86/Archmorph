import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Search } from 'lucide-react';
import { Button } from '../Button';

describe('Button', () => {
  it('uses native button keyboard semantics without submitting forms by default', async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    const onSubmit = vi.fn((event) => event.preventDefault());

    render(
      <form onSubmit={onSubmit}>
        <Button onClick={onClick}>Run analysis</Button>
      </form>,
    );

    const button = screen.getByRole('button', { name: 'Run analysis' });
    expect(button).toHaveAttribute('type', 'button');

    button.focus();
    await user.keyboard('{Enter}');
    await user.keyboard(' ');

    expect(onClick).toHaveBeenCalledTimes(2);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('blocks interaction for disabled and busy states', async () => {
    const user = userEvent.setup();
    const onDisabledClick = vi.fn();
    const onBusyClick = vi.fn();

    render(
      <>
        <Button disabled onClick={onDisabledClick}>Delete</Button>
        <Button busy onClick={onBusyClick}>Generate</Button>
      </>,
    );

    const disabledButton = screen.getByRole('button', { name: 'Delete' });
    const busyButton = screen.getByRole('button', { name: 'Generate' });

    expect(disabledButton).toBeDisabled();
    expect(busyButton).toBeDisabled();
    expect(busyButton).toHaveAttribute('aria-busy', 'true');
    expect(busyButton.querySelector('svg')).toHaveAttribute('aria-hidden', 'true');

    await user.click(disabledButton);
    await user.click(busyButton);
    expect(onDisabledClick).not.toHaveBeenCalled();
    expect(onBusyClick).not.toHaveBeenCalled();
  });

  it('supports the loading compatibility prop with the same busy semantics', () => {
    render(<Button loading>Export</Button>);

    const button = screen.getByRole('button', { name: 'Export' });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('aria-busy', 'true');
  });

  it('gives icon-only buttons an explicit accessible name and hides decorative icons', () => {
    render(<Button icon={Search} aria-label="Search services" />);

    const button = screen.getByRole('button', { name: 'Search services' });
    expect(button).toHaveAttribute('aria-label', 'Search services');
    expect(button.querySelector('svg')).toHaveAttribute('aria-hidden', 'true');
    expect(button.querySelector('svg')).toHaveAttribute('focusable', 'false');
  });
});
