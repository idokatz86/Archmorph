import React from 'react';
import { Code, Coffee, Shield } from 'lucide-react';
import { APP_VERSION } from '../constants';

export default function Footer({ handleVersionClick, setActiveTab }) {
  return (
    <footer className="border-t border-border py-8 mt-12" data-testid="footer">
      <div className="max-w-7xl mx-auto px-4">
        <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
          <p
            className="text-xs text-text-muted select-none cursor-default"
            role="button"
            tabIndex={0}
            aria-label="Version info"
            onClick={handleVersionClick}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') handleVersionClick(); }}
          >
            Archmorph v{APP_VERSION} — Translate Between Any Cloud Providers.
          </p>
          <div className="flex items-center gap-4">
            <a href="https://github.com/idokatz86/Archmorph" target="_blank" rel="noopener noreferrer" className="flex items-center gap-1.5 text-xs text-text-secondary hover:text-cta transition-colors cursor-pointer">
              <Code className="w-3.5 h-3.5" />
              GitHub
            </a>
            <a href="https://buymeacoffee.com/idokatz" target="_blank" rel="noopener noreferrer" className="flex items-center gap-1.5 text-xs text-text-secondary hover:text-amber-400 transition-colors cursor-pointer">
              <Coffee className="w-3.5 h-3.5" />
              Buy me a coffee
            </a>
            <button
              onClick={() => setActiveTab('legal')}
              className="flex items-center gap-1.5 text-xs text-text-secondary hover:text-cta transition-colors cursor-pointer"
            >
              <Shield className="w-3.5 h-3.5" />
              Legal & Privacy
            </button>
          </div>
        </div>
      </div>
    </footer>
  );
}
