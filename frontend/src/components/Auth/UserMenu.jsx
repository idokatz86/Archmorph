/**
 * UserMenu — Nav dropdown for authenticated users (#246).
 *
 * Shows avatar + name when logged in, with dropdown for Profile/Settings/Sign Out.
 * Shows "Sign In" button when not logged in.
 */

import React, { useState, useRef, useEffect } from 'react';
import { User, LogOut, Settings, ChevronDown } from 'lucide-react';
import { useAuth } from './AuthProvider';
import LoginModal from './LoginModal';
import ProfilePage from './ProfilePage';

export default function UserMenu() {
  const { user, isAuthenticated, isLoading, logout } = useAuth();
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [loginModalOpen, setLoginModalOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const menuRef = useRef(null);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClick(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setDropdownOpen(false);
      }
    }
    if (dropdownOpen) {
      document.addEventListener('mousedown', handleClick);
      return () => document.removeEventListener('mousedown', handleClick);
    }
  }, [dropdownOpen]);

  if (isLoading) {
    return (
      <div className="w-8 h-8 rounded-full bg-secondary animate-pulse" />
    );
  }

  if (!isAuthenticated) {
    return (
      <>
        <button
          onClick={() => setLoginModalOpen(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-cta hover:bg-cta/10 rounded-lg transition-colors cursor-pointer"
        >
          <User className="w-4 h-4" />
          <span className="hidden sm:inline">Sign In</span>
        </button>
        <LoginModal isOpen={loginModalOpen} onClose={() => setLoginModalOpen(false)} />
      </>
    );
  }

  const initials = (user.name || user.email || '?')
    .split(/[\s@]+/)
    .map(s => s[0])
    .slice(0, 2)
    .join('')
    .toUpperCase();

  return (
    <div className="relative" ref={menuRef}>
      <button
        onClick={() => setDropdownOpen(!dropdownOpen)}
        className="flex items-center gap-2 px-2 py-1 rounded-lg hover:bg-secondary transition-colors cursor-pointer"
        aria-label="User menu"
        aria-expanded={dropdownOpen}
      >
        {user.avatar_url ? (
          <img
            src={user.avatar_url}
            alt=""
            className="w-7 h-7 rounded-full object-cover border border-border"
          />
        ) : (
          <div className="w-7 h-7 rounded-full bg-cta/20 text-cta flex items-center justify-center text-xs font-bold">
            {initials}
          </div>
        )}
        <span className="hidden sm:inline text-sm font-medium text-text-primary max-w-[120px] truncate">
          {user.name || user.email || 'User'}
        </span>
        <ChevronDown className={`w-3.5 h-3.5 text-text-muted transition-transform ${dropdownOpen ? 'rotate-180' : ''}`} />
      </button>

      {dropdownOpen && (
        <div className="absolute right-0 top-full mt-1 w-56 bg-surface border border-border rounded-xl shadow-xl py-1 z-50">
          {/* User info header */}
          <div className="px-4 py-3 border-b border-border">
            <p className="text-sm font-medium text-text-primary truncate">{user.name || 'User'}</p>
            {user.email && (
              <p className="text-xs text-text-muted truncate">{user.email}</p>
            )}
            <p className="text-[10px] text-text-muted mt-1 uppercase tracking-wider">
              {user.provider} &middot; {user.tier || 'free'}
            </p>
          </div>

          {/* Menu items */}
          <div className="py-1">
            <button
              onClick={() => { setDropdownOpen(false); setProfileOpen(true); }}
              className="flex items-center gap-2 w-full px-4 py-2 text-sm text-text-secondary hover:text-text-primary hover:bg-secondary transition-colors cursor-pointer"
            >
              <User className="w-4 h-4" />
              Profile
            </button>
            <button
              onClick={() => setDropdownOpen(false)}
              className="flex items-center gap-2 w-full px-4 py-2 text-sm text-text-secondary hover:text-text-primary hover:bg-secondary transition-colors cursor-pointer"
            >
              <Settings className="w-4 h-4" />
              Settings
            </button>
          </div>

          <div className="border-t border-border py-1">
            <button
              onClick={() => { setDropdownOpen(false); logout(); }}
              className="flex items-center gap-2 w-full px-4 py-2 text-sm text-danger hover:bg-danger/10 transition-colors cursor-pointer"
            >
              <LogOut className="w-4 h-4" />
              Sign Out
            </button>
          </div>
        </div>
      )}
      <ProfilePage isOpen={profileOpen} onClose={() => setProfileOpen(false)} />
    </div>
  );
}
