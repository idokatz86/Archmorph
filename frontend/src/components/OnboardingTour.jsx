import React, { useState, useEffect } from 'react';
import { X, Upload, ArrowRight, Sparkles } from 'lucide-react';
import { Button, Card } from './ui';

/**
 * Wave 2: Compact 2-slide intro + contextual hints system (#514).
 *
 * - First-time visitors see a brief 2-slide welcome modal.
 * - After dismissal, contextual hints appear at key moments
 *   (managed by useContextualHint hook below).
 */

export default function OnboardingTour() {
  const [visible, setVisible] = useState(false);
  const [step, setStep] = useState(0);

  useEffect(() => {
    const seen = localStorage.getItem('archmorph-tour-seen');
    if (!seen) setVisible(true);
  }, []);

  const dismiss = () => {
    setVisible(false);
    localStorage.setItem('archmorph-tour-seen', 'true');
  };

  if (!visible) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
      <Card className="w-full max-w-md mx-4 p-6 bg-surface border border-border shadow-2xl animate-scale-in">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${step === 0 ? 'bg-cta' : 'bg-cta/40'}`} />
            <div className={`w-2 h-2 rounded-full ${step === 1 ? 'bg-cta' : 'bg-secondary'}`} />
          </div>
          <button onClick={dismiss} className="p-1 hover:bg-secondary rounded cursor-pointer" aria-label="Skip tour">
            <X className="w-4 h-4 text-text-muted" />
          </button>
        </div>

        {step === 0 ? (
          <div className="text-center py-4">
            <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-cta/10 flex items-center justify-center">
              <Sparkles className="w-8 h-8 text-cta" />
            </div>
            <h2 className="text-lg font-bold text-text-primary mb-2">Translate any cloud architecture</h2>
            <p className="text-sm text-text-secondary leading-relaxed">
              Upload an AWS or GCP diagram, and Archmorph will map it to Azure with IaC code, cost estimates, and a design document — in seconds.
            </p>
          </div>
        ) : (
          <div className="text-center py-4">
            <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-cta/10 flex items-center justify-center">
              <Upload className="w-8 h-8 text-cta" />
            </div>
            <h2 className="text-lg font-bold text-text-primary mb-2">Drop your diagram to start</h2>
            <p className="text-sm text-text-secondary leading-relaxed">
              PNG, JPG, PDF, Visio, or Draw.io — we'll handle the rest. Try a sample diagram if you don't have one ready.
            </p>
          </div>
        )}

        <div className="flex items-center justify-between mt-4">
          <Button onClick={dismiss} variant="ghost" size="sm">Skip</Button>
          {step === 0 ? (
            <Button onClick={() => setStep(1)} variant="primary" icon={ArrowRight}>Next</Button>
          ) : (
            <Button onClick={dismiss} variant="primary" icon={ArrowRight}>Get Started</Button>
          )}
        </div>
      </Card>
    </div>
  );
}

/**
 * Contextual hint — pulsing dot with tooltip, shown once per hint ID.
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
