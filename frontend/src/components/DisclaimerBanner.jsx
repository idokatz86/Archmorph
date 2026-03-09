import React, { useState, useEffect } from 'react';
import { Sparkles, X } from 'lucide-react';

export default function DisclaimerBanner() {
  const [isVisible, setIsVisible] = useState(true);

  useEffect(() => {
    // Check if user has previously dismissed the banner
    const dismissed = sessionStorage.getItem('archmorph-disclaimer-dismissed');
    if (dismissed) {
      setIsVisible(false);
    }
  }, []);

  const handleDismiss = () => {
    setIsVisible(false);
    sessionStorage.setItem('archmorph-disclaimer-dismissed', 'true');
  };

  if (!isVisible) return null;

  return (
    <div className="bg-gradient-to-r from-cta/10 via-amber-500/10 to-emerald-500/10 border-b border-cta/20 relative z-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-3">
        <div className="flex items-start sm:items-center justify-between gap-4">
          <div className="flex items-start sm:items-center gap-3">
            <div className="p-1.5 bg-cta/20 rounded-lg shrink-0">
              <Sparkles className="w-4 h-4 text-cta" />
            </div>
            <p className="text-xs sm:text-sm text-text-primary">
              <strong className="font-semibold text-cta">Welcome to Archmorph!</strong>{' '}
              This is a passionate <em>"vibe-coding"</em> project in active development. 
              We're constantly shipping new features, so please treat this free-of-charge tool <span className="font-semibold">"as-is"</span>. 
              Enjoy exploring, and pardon our dust while we keep building! 🛠️
            </p>
          </div>
          <button
            onClick={handleDismiss}
            className="p-1.5 hover:bg-surface/50 rounded-lg text-text-muted hover:text-text-primary transition-colors shrink-0"
            aria-label="Dismiss disclaimer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
