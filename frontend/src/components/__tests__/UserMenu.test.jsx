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

const authMock = vi.hoisted(() => ({
  logout: vi.fn(),
  state: {
    user: null,
    isAuthenticated: false,
    isLoading: false,
    logout: vi.fn(),
  },
}));

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
  useAuth: () => authMock.state,
}));

import UserMenu from '../Auth/UserMenu';

describe('UserMenu — Sign In button', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authMock.logout = vi.fn();
    authMock.state = {
      user: null,
      isAuthenticated: false,
      isLoading: false,
      logout: authMock.logout,
    };
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

describe('UserMenu — authenticated dropdown', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authMock.logout = vi.fn();
    authMock.state = {
      user: {
        name: 'Ido Katz',
        email: 'ido@example.com',
        provider: 'microsoft',
      },
      isAuthenticated: true,
      isLoading: false,
      logout: authMock.logout,
    };
  });

  it('uses menu semantics on the trigger and dropdown items', async () => {
    const user = userEvent.setup();
    render(<UserMenu />);

    const trigger = screen.getByRole('button', { name: /user menu/i });
    expect(trigger).toHaveAttribute('aria-haspopup', 'menu');
    expect(trigger).toHaveAttribute('aria-expanded', 'false');

    await user.click(trigger);

    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('menu', { name: /user menu/i })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: /profile/i })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: /settings/i })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: /sign out/i })).toBeInTheDocument();
  });

  it('opens with ArrowDown and roves focus through menu items', async () => {
    const user = userEvent.setup();
    render(<UserMenu />);

    const trigger = screen.getByRole('button', { name: /user menu/i });
    trigger.focus();
    await user.keyboard('{ArrowDown}');

    expect(screen.getByRole('menuitem', { name: /profile/i })).toHaveFocus();

    await user.keyboard('{ArrowDown}');
    expect(screen.getByRole('menuitem', { name: /settings/i })).toHaveFocus();

    await user.keyboard('{ArrowUp}');
    expect(screen.getByRole('menuitem', { name: /profile/i })).toHaveFocus();
  });

  it('supports Home, End, and Tab keyboard behavior', async () => {
    const user = userEvent.setup();
    render(<UserMenu />);

    const trigger = screen.getByRole('button', { name: /user menu/i });
    trigger.focus();
    await user.keyboard('{ArrowDown}');

    await user.keyboard('{End}');
    expect(screen.getByRole('menuitem', { name: /sign out/i })).toHaveFocus();

    await user.keyboard('{Home}');
    expect(screen.getByRole('menuitem', { name: /profile/i })).toHaveFocus();

    await user.keyboard('{Tab}');
    expect(screen.queryByRole('menu', { name: /user menu/i })).not.toBeInTheDocument();
  });

  it('closes on Escape and restores focus to the trigger', async () => {
    const user = userEvent.setup();
    render(<UserMenu />);

    const trigger = screen.getByRole('button', { name: /user menu/i });
    await user.click(trigger);
    await user.keyboard('{Escape}');

    expect(screen.queryByRole('menu', { name: /user menu/i })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it('calls logout from the Sign Out menu item', async () => {
    const user = userEvent.setup();
    render(<UserMenu />);

    await user.click(screen.getByRole('button', { name: /user menu/i }));
    await user.click(screen.getByRole('menuitem', { name: /sign out/i }));

    expect(authMock.logout).toHaveBeenCalledTimes(1);
  });
});
