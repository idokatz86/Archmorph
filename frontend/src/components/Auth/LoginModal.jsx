/**
 * LoginModal — Social sign-in modal (#246).
 *
 * Offers Microsoft, Google, GitHub sign-in buttons
 * plus "Continue as Guest" — all using Azure SWA auth redirects.
 */

import React from 'react';
import { X } from 'lucide-react';
import { useAuth } from './AuthProvider';

/* Simple inline SVG provider icons — avoids external dependency */
function MicrosoftIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 21 21" fill="none">
      <rect x="1" y="1" width="9" height="9" fill="#F25022" />
      <rect x="11" y="1" width="9" height="9" fill="#7FBA00" />
      <rect x="1" y="11" width="9" height="9" fill="#00A4EF" />
      <rect x="11" y="11" width="9" height="9" fill="#FFB900" />
    </svg>
  );
}

function GoogleIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 24 24">
      <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4" />
      <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
      <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05" />
      <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335" />
    </svg>
  );
}

function GitHubIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z" />
    </svg>
  );
}

const PROVIDERS = [
  {
    id: 'microsoft',
    label: 'Continue with Microsoft',
    Icon: MicrosoftIcon,
    bg: 'bg-white hover:bg-gray-50 dark:bg-gray-800 dark:hover:bg-gray-700',
    text: 'text-gray-800 dark:text-gray-100',
    border: 'border-gray-300 dark:border-gray-600',
  },
  {
    id: 'google',
    label: 'Continue with Google',
    Icon: GoogleIcon,
    bg: 'bg-white hover:bg-gray-50 dark:bg-gray-800 dark:hover:bg-gray-700',
    text: 'text-gray-800 dark:text-gray-100',
    border: 'border-gray-300 dark:border-gray-600',
  },
  {
    id: 'github',
    label: 'Continue with GitHub',
    Icon: GitHubIcon,
    bg: 'bg-gray-900 hover:bg-gray-800 dark:bg-gray-700 dark:hover:bg-gray-600',
    text: 'text-white',
    border: 'border-gray-900 dark:border-gray-600',
  },
];

export default function LoginModal({ isOpen, onClose }) {
  const { loginWithProvider } = useAuth();

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />
      {/* Modal */}
      <div className="relative z-10 w-full max-w-sm mx-4 bg-surface border border-border rounded-2xl shadow-2xl p-6">
        {/* Close button */}
        <button
          onClick={onClose}
          className="absolute top-3 right-3 p-1.5 rounded-lg hover:bg-secondary transition-colors cursor-pointer"
          aria-label="Close"
        >
          <X className="w-4 h-4 text-text-muted" />
        </button>

        {/* Header */}
        <div className="text-center mb-6">
          <h2 className="text-xl font-bold text-text-primary">Sign in to Archmorph</h2>
          <p className="text-sm text-text-muted mt-1">Save your work, unlock features</p>
        </div>

        {/* Provider buttons */}
        <div className="space-y-3">
          {PROVIDERS.map(({ id, label, Icon, bg, text, border }) => (
            <button
              key={id}
              onClick={() => loginWithProvider(id)}
              className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg border ${border} ${bg} ${text} font-medium text-sm transition-all duration-200 cursor-pointer`}
            >
              <Icon className="w-5 h-5 flex-shrink-0" />
              {label}
            </button>
          ))}
        </div>

        {/* Divider */}
        <div className="flex items-center gap-3 my-5">
          <div className="flex-1 h-px bg-border" />
          <span className="text-xs text-text-muted">or</span>
          <div className="flex-1 h-px bg-border" />
        </div>

        {/* Continue as Guest */}
        <button
          onClick={onClose}
          className="w-full px-4 py-2.5 text-sm font-medium text-text-secondary hover:text-text-primary rounded-lg hover:bg-secondary transition-colors cursor-pointer"
        >
          Continue as Guest
        </button>

        <p className="text-[11px] text-text-muted text-center mt-4">
          No account needed to use the translator. Sign in to save your work.
        </p>
      </div>
    </div>
  );
}
