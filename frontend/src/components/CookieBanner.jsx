import React, { useState, useEffect } from 'react';
import { Cookie, X, ChevronDown, ChevronUp } from 'lucide-react';
import useAppStore from '../stores/useAppStore';

const CONSENT_STORAGE_KEY = 'archmorph_cookie_consent';

function getStoredConsent() {
  try {
    const raw = localStorage.getItem(CONSENT_STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function storeConsent(consent) {
  try {
    localStorage.setItem(CONSENT_STORAGE_KEY, JSON.stringify({
      ...consent,
      timestamp: new Date().toISOString(),
    }));
  } catch {
    // localStorage unavailable
  }
}

export default function CookieBanner() {
  const [visible, setVisible] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [consent, setConsent] = useState({
    necessary: true,
    analytics: false,
    marketing: false,
    functional: false,
  });

  useEffect(() => {
    const stored = getStoredConsent();
    if (!stored) {
      // Small delay so it doesn't flash on load
      const timer = setTimeout(() => setVisible(true), 1000);
      return () => clearTimeout(timer);
    }
  }, []);

  if (!visible) return null;

  const handleAcceptAll = () => {
    const full = { necessary: true, analytics: true, marketing: true, functional: true };
    storeConsent(full);
    setVisible(false);
  };

  const handleAcceptNecessary = () => {
    const minimal = { necessary: true, analytics: false, marketing: false, functional: false };
    storeConsent(minimal);
    setVisible(false);
  };

  const handleSavePreferences = () => {
    storeConsent({ ...consent, necessary: true });
    setVisible(false);
  };

  const toggleCategory = (key) => {
    if (key === 'necessary') return; // Cannot disable
    setConsent(prev => ({ ...prev, [key]: !prev[key] }));
  };

  return (
    <div
      className="fixed bottom-0 left-0 right-0 z-[60] bg-surface border-t border-border shadow-2xl"
      role="dialog"
      aria-label="Cookie consent"
      data-testid="cookie-banner"
    >
      <div className="max-w-5xl mx-auto px-4 py-4">
        <div className="flex items-start gap-3">
          <Cookie className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <p className="text-sm text-text-primary font-medium">Cookie Preferences</p>
            <p className="text-xs text-text-muted mt-1">
              We use cookies to ensure the best experience. Necessary cookies are required for site
              functionality. You can customize your preferences below.{' '}
              <a
                href="#"
                onClick={(e) => { e.preventDefault(); useAppStore.getState().setActiveTab('legal'); setVisible(false); }}
                className="text-cta hover:underline"
              >
                Cookie Policy
              </a>
            </p>

            {expanded && (
              <div className="mt-3 space-y-2">
                {[
                  { key: 'necessary', label: 'Necessary', desc: 'Required for site operation', locked: true },
                  { key: 'analytics', label: 'Analytics', desc: 'Help us understand how you use the site' },
                  { key: 'functional', label: 'Functional', desc: 'Enable enhanced features and personalization' },
                  { key: 'marketing', label: 'Marketing', desc: 'Used for targeted content and advertising' },
                ].map(cat => (
                  <label
                    key={cat.key}
                    className="flex items-center gap-3 p-2 rounded-lg hover:bg-secondary/50 cursor-pointer"
                  >
                    <input
                      type="checkbox"
                      checked={consent[cat.key]}
                      onChange={() => toggleCategory(cat.key)}
                      disabled={cat.locked}
                      className="w-4 h-4 rounded border-border text-cta accent-cta"
                    />
                    <div>
                      <span className="text-sm text-text-primary font-medium">{cat.label}</span>
                      {cat.locked && <span className="text-[10px] text-text-muted ml-1">(always on)</span>}
                      <p className="text-xs text-text-muted">{cat.desc}</p>
                    </div>
                  </label>
                ))}
              </div>
            )}
          </div>
          <button
            onClick={() => setVisible(false)}
            className="p-1 rounded hover:bg-secondary transition-colors"
            aria-label="Dismiss cookie banner"
          >
            <X className="w-4 h-4 text-text-muted" />
          </button>
        </div>

        <div className="flex items-center justify-between mt-3 pt-3 border-t border-border/50">
          <button
            onClick={() => setExpanded(prev => !prev)}
            className="flex items-center gap-1 text-xs text-text-secondary hover:text-text-primary transition-colors"
          >
            {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
            {expanded ? 'Hide details' : 'Customize'}
          </button>
          <div className="flex items-center gap-2">
            <button
              onClick={handleAcceptNecessary}
              className="px-3 py-1.5 text-xs font-medium text-text-secondary border border-border rounded-lg hover:bg-secondary transition-colors"
            >
              Necessary only
            </button>
            {expanded && (
              <button
                onClick={handleSavePreferences}
                className="px-3 py-1.5 text-xs font-medium text-text-secondary border border-border rounded-lg hover:bg-secondary transition-colors"
              >
                Save preferences
              </button>
            )}
            <button
              onClick={handleAcceptAll}
              className="px-3 py-1.5 text-xs font-medium text-white bg-cta rounded-lg hover:bg-cta/90 transition-colors"
            >
              Accept all
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
