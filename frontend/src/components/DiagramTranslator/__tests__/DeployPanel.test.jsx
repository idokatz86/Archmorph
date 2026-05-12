import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import DeployPanel from '../DeployPanel';

describe('DeployPanel coming-soon state', () => {
  it('announces the deployment feature as coming soon', () => {
    render(<DeployPanel />);

    expect(screen.getByRole('status', {
      name: /coming soon.*one-click deployment is under active development/i,
    })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /coming soon/i })).toBeInTheDocument();
  });

  it('does not render hidden interactive preview controls while disabled', () => {
    const { container } = render(<DeployPanel />);

    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(container.querySelector('[aria-hidden="true"] button')).not.toBeInTheDocument();
  });

  it('uses app theme tokens instead of Tailwind dark variants', () => {
    const { container } = render(<DeployPanel />);
    const status = screen.getByRole('status');

    expect(status.className).toContain('bg-surface');
    expect(status.className).toContain('border-border');
    expect(container.innerHTML).not.toContain('dark:');
    expect(container.innerHTML).not.toContain('bg-gray-');
    expect(container.innerHTML).not.toContain('text-gray-');
  });
});