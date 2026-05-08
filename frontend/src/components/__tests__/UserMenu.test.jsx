/**
 * UserMenu regression tests (#803 #805 #808 #816 #817 #818).
 *
 * Covers: Sign In button a11y (aria-haspopup, aria-expanded, aria-label,
 * 44px touch target), LoginModal opens/closes.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';

// Stub LoginModal so we don't need its full dependency tree
vi.mock('../Auth/LoginModal', () => ({
  default: ({ isOpen, onClose }) =>
    isOpen ? (
      <div role="dialog" aria-label="Sign in">
        <button onClick={onClose}>Close</button>
      </div>
    ) : null,
}));

// Stub ProfilePage
vi.mock('../Auth/ProfilePage', () => ({
  default: () => null,
}));

vi.mock('../Auth/AuthProvider', () => ({
  useAuth: () => ({
    user: null,
    isAuthenticated: false,
    isLoading: false,
    logout: vi.fn(),
  }),
}));

import UserMenu from '../Auth/UserMenu';

describe('UserMenu — Sign In button', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the Sign In button when unauthenticated', () => {
    render(<UserMenu />);
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
  });

  it('Sign In button has aria-haspopup="dialog"', () => {
    render(<UserMenu />);
    const btn = screen.getByRole('button', { name: /sign in/i });
    expect(btn).toHaveAttribute('aria-haspopup', 'dialog');
  });

  it('Sign In button has aria-expanded=false when modal is closed', () => {
    render(<UserMenu />);
    const btn = screen.getByRole('button', { name: /sign in/i });
    expect(btn).toHaveAttribute('aria-expanded', 'false');
  });

  it('Sign In button has aria-expanded=true when modal is open', async () => {
    render(<UserMenu />);
    const btn = screen.getByRole('button', { name: /sign in/i });
    await userEvent.click(btn);
    expect(btn).toHaveAttribute('aria-expanded', 'true');
  });

  it('Sign In button has a 44px min-height touch target class', () => {
    render(<UserMenu />);
    const btn = screen.getByRole('button', { name: /sign in/i });
    expect(btn.className).toContain('min-h-11');
    expect(btn.className).toContain('min-w-11');
  });

  it('opens the LoginModal when Sign In is clicked', async () => {
    render(<UserMenu />);
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });
});
