import React from 'react';
import { FileQuestion } from 'lucide-react';
import { Button } from './ui';

export default function EmptyState({ 
  icon: Icon = FileQuestion, 
  title, 
  description, 
  actionLabel, 
  onAction,
  children,
  className = ''
}) {
  return (
    <div className={`flex flex-col items-center justify-center py-16 px-6 text-center bg-secondary/50 rounded-xl border border-border border-dashed my-8 max-w-3xl mx-auto animate-fade-in ${className}`}>
      <div className="w-14 h-14 rounded-2xl bg-secondary border border-border flex items-center justify-center mb-5">
        <Icon className="w-7 h-7 text-text-muted" />
      </div>
      {title && <h3 className="text-lg font-semibold text-text-primary mb-2">{title}</h3>}
      {description && <p className="text-sm text-text-muted max-w-md mb-6 leading-relaxed">{description}</p>}
      {actionLabel && onAction && (
        <Button onClick={onAction} variant="primary" size="md">{actionLabel}</Button>
      )}
      {children && (
        <div className="mt-8 w-full max-w-2xl text-left bg-surface p-6 rounded-xl border border-border shadow-sm">
          {children}
        </div>
      )}
    </div>
  );
}