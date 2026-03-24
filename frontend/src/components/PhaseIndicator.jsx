import React from 'react';
import { Check } from 'lucide-react';

const DEFAULT_PHASES = [
  { label: 'Input' },
  { label: 'Analysis' },
  { label: 'Deliverables' },
];

export default function PhaseIndicator({ currentPhase = 1, phases = DEFAULT_PHASES, className = '' }) {
  return (
    <div className={`flex items-center gap-2 ${className}`} role="navigation" aria-label="Progress">
      {phases.map((phase, idx) => {
        const step = idx + 1;
        const isCompleted = step < currentPhase;
        const isActive = step === currentPhase;
        const isUpcoming = step > currentPhase;
        const PhaseIcon = phase.icon;

        return (
          <React.Fragment key={step}>
            {idx > 0 && (
              <div className={`flex-1 h-px transition-colors duration-300 ${isCompleted ? 'bg-cta' : 'bg-border'}`} />
            )}
            <div className="flex items-center gap-2">
              <div
                className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold transition-all duration-300 ${
                  isCompleted
                    ? 'bg-cta text-surface'
                    : isActive
                      ? 'bg-cta/15 text-cta border-2 border-cta animate-pulse-once'
                      : 'bg-secondary text-text-muted border border-border'
                }`}
                aria-current={isActive ? 'step' : undefined}
              >
                {isCompleted ? (
                  <Check className="w-4 h-4" />
                ) : PhaseIcon ? (
                  <PhaseIcon className="w-4 h-4" />
                ) : (
                  step
                )}
              </div>
              <span
                className={`text-sm font-medium hidden sm:inline transition-colors duration-200 ${
                  isCompleted ? 'text-cta' : isActive ? 'text-text-primary' : 'text-text-muted'
                }`}
              >
                {phase.label}
              </span>
            </div>
          </React.Fragment>
        );
      })}
    </div>
  );
}
