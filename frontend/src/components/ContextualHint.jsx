import React, { useState, useEffect } from 'react';
import { X } from 'lucide-react';

/**
 * Contextual hint — pulsing dot with tooltip, shown once per hint ID.
 *
 * Extracted from the now-removed OnboardingTour (CTO PR-1, May 2026).
 * The marketing intro modal is gone; this small reusable hint primitive
 * stays because it's used inside the spine flow (DiagramTranslator's
 * UploadStep, ResultsTable, IaCViewer) to point engineers at non-obvious
 * affordances on first encounter.
 *
 * Usage:
 *   <ContextualHint id="upload-prompt" content="Drop any cloud diagram here" position="bottom">
 *     <UploadZone />
 *   </ContextualHint>
 */
export function ContextualHint({ id, content, position = 'bottom', children }) {
  const storageKey = `archmorph-hint-${id}`;
  const [dismissed, setDismissed] = useState(() => {
    return typeof window !== 'undefined' && localStorage.getItem(storageKey) === 'true';
  });
  const [show, setShow] = useState(false);

  useEffect(() => {
    if (dismissed) return;
    const timer = setTimeout(() => setShow(true), 1000); // appear after 1s
    return () => clearTimeout(timer);
  }, [dismissed]);

  const dismiss = () => {
    setDismissed(true);
    setShow(false);
    localStorage.setItem(storageKey, 'true');
  };

  const positions = {
    top: 'bottom-full left-1/2 -translate-x-1/2 mb-3',
    bottom: 'top-full left-1/2 -translate-x-1/2 mt-3',
    right: 'left-full top-1/2 -translate-y-1/2 ml-3',
  };

  return (
    <div className="relative">
      {children}
      {show && !dismissed && (
        <>
          {/* Pulsing dot */}
          <span className="absolute -top-1 -right-1 w-3 h-3 rounded-full bg-cta animate-pulse z-10" />
          {/* Tooltip */}
          <div className={`absolute z-20 ${positions[position]} animate-scale-in`}>
            <div className="flex items-center gap-2 px-3 py-2 bg-secondary border border-border rounded-lg shadow-lg text-xs text-text-primary whitespace-nowrap">
              <span>{content}</span>
              <button onClick={dismiss} className="p-0.5 hover:bg-primary rounded cursor-pointer" aria-label="Dismiss hint">
                <X className="w-3 h-3 text-text-muted" />
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export default ContextualHint;
