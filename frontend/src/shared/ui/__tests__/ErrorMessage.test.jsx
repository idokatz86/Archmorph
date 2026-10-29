import React from 'react';
import { run as runAxe } from 'axe-core';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ErrorMessage } from '../ErrorMessage';

describe('ErrorMessage', () => {
  it('announces urgent errors assertively and exposes the recovery action', async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();

    render(
      <ErrorMessage
        title="Templates unavailable"
        message="The starter architectures could not be loaded."
        onAction={onAction}
        actionLabel="Try loading again"
      />,
    );

    const alert = screen.getByRole('alert');
    expect(alert).toHaveAttribute('aria-atomic', 'true');
    expect(alert).toHaveTextContent('Templates unavailable');
    expect(alert).toHaveTextContent('The starter architectures could not be loaded.');

    await user.click(screen.getByRole('button', { name: 'Try loading again' }));
    expect(onAction).toHaveBeenCalledTimes(1);
  });

  it('uses polite status semantics for non-urgent updates', () => {
    render(
      <ErrorMessage
        announcement="polite"
        title="Export delayed"
        message="The export is still being prepared."
      />,
    );

    expect(screen.getByRole('status')).toHaveTextContent('Export delayed');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('has no serious or critical axe violations', async () => {
    const { container } = render(
      <ErrorMessage
        title="Templates unavailable"
        message="The starter architectures could not be loaded."
        onAction={() => {}}
        actionLabel="Try loading again"
      />,
    );

    const { violations } = await runAxe(container);
    expect(violations.filter(({ impact }) => impact === 'serious' || impact === 'critical')).toEqual([]);
  });
});
