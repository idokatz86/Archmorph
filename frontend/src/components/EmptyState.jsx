import React from 'react';

export default function EmptyState({ 
  icon: Icon, 
  title, 
  description, 
  actionLabel, 
  onAction,
  children
}) {
  return (
    <div className="flex flex-col items-center justify-center py-20 px-4 text-center bg-surface-alt rounded-xl border border-border border-dashed my-8 max-w-3xl mx-auto">
      <div className="bg-surface p-4 rounded-full shadow-sm mb-6 border border-border text-cta">
        {Icon && <Icon className="w-8 h-8" />}
      </div>
      <h3 className="text-xl font-semibold text-text-primary mb-2">{title}</h3>
      <p className="text-text-secondary max-w-lg mb-8 text-sm leading-relaxed">
        {description}
      </p>
      {actionLabel && onAction && (
        <button
          onClick={onAction}
          className="bg-cta text-surface px-6 py-2.5 rounded-lg text-sm font-medium hover:bg-opacity-90 transition-colors shadow-sm focus:outline-none focus:ring-2 focus:ring-cta focus:ring-offset-2"
        >
          {actionLabel}
        </button>
      )}
      {children && (
        <div className="mt-8 w-full max-w-2xl text-left bg-surface p-6 rounded-xl border border-border shadow-sm">
          {children}
        </div>
      )}
    </div>
  );
}