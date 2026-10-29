import React from 'react';
import { AlertCircle } from 'lucide-react';
import { Button } from './Button';

const announcementRoles = {
  assertive: 'alert',
  polite: 'status',
};

export function ErrorMessage({
  title = 'Something went wrong',
  message,
  onAction,
  actionLabel = 'Try Again',
  announcement = 'assertive',
  className = '',
}) {
  const role = announcementRoles[announcement];

  if (!role) {
    throw new Error('ErrorMessage announcement must be "assertive" or "polite"');
  }

  return (
    <div
      role={role}
      aria-atomic="true"
      className={`bg-primary border border-border rounded-xl p-6 border-danger/30 animate-fade-in ${className}`}
    >
      <div className="flex flex-col items-center text-center gap-3">
        <div className="w-10 h-10 rounded-full bg-danger/15 flex items-center justify-center">
          <AlertCircle className="w-5 h-5 text-danger" aria-hidden="true" />
        </div>
        <div>
          <h3 className="text-sm font-semibold text-text-primary">{title}</h3>
          {message && <p className="text-xs text-text-muted mt-1">{message}</p>}
        </div>
        {onAction && (
          <Button variant="secondary" size="sm" onClick={onAction}>
            {actionLabel}
          </Button>
        )}
      </div>
    </div>
  );
}
