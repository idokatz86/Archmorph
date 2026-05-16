/**
 * LoginModal regression tests (#803 #805 #807 #808 #814 #815 #816 #817
 * #818 #819 #820 #821 #822 #853 #854 #907 #908).
 *
 * Covers: portal rendering, ARIA semantics, Escape close, backdrop click,
 * body scroll lock, focus trap, and browsing-only dismissal.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';

// Mock useAuth so we can control loginWithProvider
const mockLoginWithProvider = vi.fn();
vi.mock('../Auth/AuthProvider', () => ({
  useAuth: () => ({
    loginWithProvider: mockLoginWithProvider,
  }),
}));

import LoginModal from '../Auth/LoginModal';

describe('LoginModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Reset scroll lock
    document.body.style.overflow = '';
  });

  afterEach(() => {
    document.body.style.overflow = '';
  });

  it('renders nothing when isOpen=false', () => {
    render(<LoginModal isOpen={false} onClose={vi.fn()} />);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('portals the dialog to document.body (not inline in render root)', () => {
    const { container } = render(<LoginModal isOpen={true} onClose={vi.fn()} />);
    // The dialog should NOT be inside the component's render container
    expect(container.querySelector('[role="dialog"]')).toBeNull();
    // But it should be in document.body
    const dialog = document.body.querySelector('[role="dialog"]');
    expect(dialog).not.toBeNull();
  });

  it('has role=dialog, aria-modal=true, and aria-labelledby pointing to heading', () => {
    render(<LoginModal isOpen={true} onClose={vi.fn()} />);
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    const labelId = dialog.getAttribute('aria-labelledby');
    expect(labelId).toBeTruthy();
    const heading = document.getElementById(labelId);
    expect(heading).not.toBeNull();
    expect(heading.textContent).toContain('Sign in to Archmorph');
  });

  it('calls onClose when Escape is pressed', async () => {
    const onClose = vi.fn();
    render(<LoginModal isOpen={true} onClose={onClose} />);
    await userEvent.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('calls onClose when backdrop is clicked', async () => {
    const onClose = vi.fn();
    render(<LoginModal isOpen={true} onClose={onClose} />);
    // The backdrop is aria-hidden; click on the fixed overlay behind the dialog
    const backdrop = document.body.querySelector('[aria-hidden="true"]');
    await userEvent.click(backdrop);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('calls onClose when Close button is clicked', async () => {
    const onClose = vi.fn();
    render(<LoginModal isOpen={true} onClose={onClose} />);
    await userEvent.click(screen.getByRole('button', { name: /^close$/i }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('calls onClose when Continue Browsing is clicked', async () => {
    const onClose = vi.fn();
    render(<LoginModal isOpen={true} onClose={onClose} />);
    await userEvent.click(screen.getByRole('button', { name: /continue browsing/i }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('makes clear that diagram analysis requires sign-in', () => {
    render(<LoginModal isOpen={true} onClose={vi.fn()} />);
    expect(screen.getByText(/sign in is required to analyze diagrams/i)).toBeInTheDocument();
    expect(screen.queryByText(/no account needed to use the translator/i)).not.toBeInTheDocument();
  });

  it('locks body scroll when open and restores on close', () => {
    const { rerender } = render(<LoginModal isOpen={true} onClose={vi.fn()} />);
    expect(document.body.style.overflow).toBe('hidden');
    rerender(<LoginModal isOpen={false} onClose={vi.fn()} />);
    // beforeEach resets to '' — confirm exact restoration
    expect(document.body.style.overflow).toBe('');
  });

  it('shows all provider sign-in buttons', () => {
    render(<LoginModal isOpen={true} onClose={vi.fn()} />);
    expect(screen.getByRole('button', { name: /continue with microsoft/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /continue with google/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /continue with github/i })).toBeInTheDocument();
  });

  it('warns and blocks provider redirect when selected upload warning is cancelled', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(
      <LoginModal
        isOpen={true}
        onClose={vi.fn()}
        selectedFile={{ name: 'architecture.pdf', size: 1024, type: 'application/pdf' }}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: /continue with github/i }));

    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(mockLoginWithProvider).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it('persists redirect recovery metadata before provider navigation when warning is accepted', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    const onBeforeProviderRedirect = vi.fn();
    render(
      <LoginModal
        isOpen={true}
        onClose={vi.fn()}
        selectedFile={{ name: 'architecture.pdf', size: 1024, type: 'application/pdf', lastModified: 123 }}
        onBeforeProviderRedirect={onBeforeProviderRedirect}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: /continue with github/i }));

    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(onBeforeProviderRedirect).toHaveBeenCalledWith({
      name: 'architecture.pdf',
      size: 1024,
      type: 'application/pdf',
      lastModified: 123,
    });
    expect(mockLoginWithProvider).toHaveBeenCalledWith('github');
    confirmSpy.mockRestore();
  });

  it('uses app theme tokens instead of Tailwind dark variants', () => {
    render(<LoginModal isOpen={true} onClose={vi.fn()} />);
    const dialog = screen.getByRole('dialog');

    expect(dialog.className).toContain('bg-surface');
    expect(dialog.className).toContain('border-border');
    expect(document.body.innerHTML).not.toContain('dark:');
    expect(document.body.innerHTML).not.toContain('bg-gray-');
    expect(document.body.innerHTML).not.toContain('text-gray-');
  });
});
