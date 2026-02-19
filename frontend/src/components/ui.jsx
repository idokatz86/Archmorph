import React from 'react';
import { Loader2 } from 'lucide-react';

export function Badge({ children, variant = 'default' }) {
  const styles = {
    high: 'bg-cta/15 text-cta border-cta/30',
    medium: 'bg-warning/15 text-warning border-warning/30',
    low: 'bg-danger/15 text-danger border-danger/30',
    aws: 'bg-[#FF9900]/15 text-[#FF9900] border-[#FF9900]/30',
    azure: 'bg-info/15 text-info border-info/30',
    gcp: 'bg-[#EA4335]/15 text-[#EA4335] border-[#EA4335]/30',
    default: 'bg-secondary text-text-secondary border-border',
  };
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-md border ${styles[variant] || styles.default}`}>
      {children}
    </span>
  );
}

export function Button({ children, onClick, variant = 'primary', size = 'md', disabled, loading, icon: Icon, className = '' }) {
  const base = 'inline-flex items-center justify-center gap-2 font-semibold rounded-lg transition-all duration-200 cursor-pointer select-none disabled:opacity-40 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-cta/50';
  const variants = {
    primary: 'bg-cta hover:bg-cta-hover text-surface shadow-lg shadow-cta/20',
    secondary: 'bg-secondary hover:bg-border-light text-text-primary border border-border',
    ghost: 'hover:bg-secondary text-text-secondary hover:text-text-primary',
    danger: 'bg-danger/15 hover:bg-danger/25 text-danger border border-danger/30',
  };
  const sizes = { sm: 'px-3 py-1.5 text-xs', md: 'px-4 py-2 text-sm', lg: 'px-6 py-3 text-base' };
  return (
    <button onClick={onClick} disabled={disabled || loading} className={`${base} ${variants[variant]} ${sizes[size]} ${className}`}>
      {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : Icon && <Icon className="w-4 h-4" />}
      {children}
    </button>
  );
}

export function Card({ children, className = '', hover = false }) {
  return (
    <div className={`bg-primary border border-border rounded-xl ${hover ? 'hover:border-border-light transition-colors duration-200 cursor-pointer' : ''} ${className}`}>
      {children}
    </div>
  );
}
