import React, { forwardRef } from 'react';
import { Loader2, AlertCircle, FileQuestion } from 'lucide-react';

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

export function Button({ children, onClick, variant = 'primary', size = 'md', disabled, loading, icon: Icon, className = '', ...rest }) {
  const base = 'inline-flex items-center justify-center gap-2 font-semibold rounded-lg transition-all duration-200 cursor-pointer select-none disabled:opacity-40 disabled:cursor-not-allowed active:scale-[0.97] focus:outline-none focus:ring-2 focus:ring-cta/50';
  const variants = {
    primary: 'bg-cta hover:bg-cta-hover text-surface shadow-lg shadow-cta/20',
    secondary: 'bg-secondary hover:bg-border-light text-text-primary border border-border',
    ghost: 'hover:bg-secondary text-text-secondary hover:text-text-primary',
    danger: 'bg-danger/15 hover:bg-danger/25 text-danger border border-danger/30',
  };
  const sizes = { sm: 'px-3 py-1.5 text-xs', md: 'px-4 py-2 text-sm', lg: 'px-6 py-3 text-base' };
  return (
    <button onClick={onClick} disabled={disabled || loading} className={`${base} ${variants[variant]} ${sizes[size]} ${className}`} {...rest}>
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

/* ── Wave 1: New primitives (#510) ── */

export const Input = forwardRef(function Input({ label, error, helpText, icon: Icon, className = '', id, ...rest }, ref) {
  const inputId = id || (label ? label.toLowerCase().replace(/\s+/g, '-') : undefined);
  const errorId = error ? `${inputId}-error` : undefined;
  const helpId = helpText && !error ? `${inputId}-help` : undefined;
  return (
    <div className={`flex flex-col gap-1 ${className}`}>
      {label && <label htmlFor={inputId} className="text-sm font-medium text-text-secondary">{label}</label>}
      <div className="relative">
        {Icon && <Icon className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-muted pointer-events-none" />}
        <input
          ref={ref}
          id={inputId}
          aria-invalid={error ? 'true' : undefined}
          aria-describedby={errorId || helpId || undefined}
          className={`w-full h-9 px-3 ${Icon ? 'pl-9' : ''} text-sm bg-secondary border rounded-lg text-text-primary placeholder:text-text-muted transition-colors duration-150 focus:outline-none focus:ring-2 focus:ring-cta/50 focus:border-cta ${
            error ? 'border-danger ring-1 ring-danger/30' : 'border-border hover:border-border-light'
          }`}
          {...rest}
        />
      </div>
      {error && <p id={errorId} className="text-xs text-danger flex items-center gap-1"><AlertCircle className="w-3 h-3" />{error}</p>}
      {helpText && !error && <p id={helpId} className="text-xs text-text-muted">{helpText}</p>}
    </div>
  );
});

export const Select = forwardRef(function Select({ label, error, helpText, options = [], placeholder, className = '', id, ...rest }, ref) {
  const selectId = id || (label ? label.toLowerCase().replace(/\s+/g, '-') : undefined);
  const errorId = error ? `${selectId}-error` : undefined;
  return (
    <div className={`flex flex-col gap-1 ${className}`}>
      {label && <label htmlFor={selectId} className="text-sm font-medium text-text-secondary">{label}</label>}
      <select
        ref={ref}
        id={selectId}
        aria-invalid={error ? 'true' : undefined}
        aria-describedby={errorId || undefined}
        className={`w-full h-9 px-3 text-sm bg-secondary border rounded-lg text-text-primary transition-colors duration-150 focus:outline-none focus:ring-2 focus:ring-cta/50 focus:border-cta cursor-pointer ${
          error ? 'border-danger ring-1 ring-danger/30' : 'border-border hover:border-border-light'
        }`}
        {...rest}
      >
        {placeholder && <option value="">{placeholder}</option>}
        {options.map(opt => (
          <option key={opt.value} value={opt.value}>{opt.label}</option>
        ))}
      </select>
      {error && <p id={errorId} className="text-xs text-danger flex items-center gap-1"><AlertCircle className="w-3 h-3" />{error}</p>}
      {helpText && !error && <p className="text-xs text-text-muted">{helpText}</p>}
    </div>
  );
});

export function Skeleton({ className = '', variant = 'text' }) {
  const variants = {
    text: 'skeleton skeleton-text',
    heading: 'skeleton skeleton-heading',
    card: 'skeleton skeleton-card',
    circle: 'skeleton rounded-full',
  };
  return <div className={`${variants[variant] || variants.text} ${className}`} aria-hidden="true" />;
}

export function EmptyState({ icon: Icon = FileQuestion, title, description, action, className = '' }) {
  return (
    <div className={`flex flex-col items-center justify-center py-12 px-6 text-center ${className}`}>
      <div className="w-12 h-12 rounded-xl bg-secondary flex items-center justify-center mb-4">
        <Icon className="w-6 h-6 text-text-muted" />
      </div>
      {title && <h3 className="text-base font-semibold text-text-primary mb-1">{title}</h3>}
      {description && <p className="text-sm text-text-muted max-w-sm mb-4">{description}</p>}
      {action}
    </div>
  );
}

export function ErrorCard({ title = 'Something went wrong', message, onRetry, retryLabel = 'Try Again' }) {
  return (
    <Card className="p-6 border-danger/30 animate-fade-in">
      <div className="flex flex-col items-center text-center gap-3">
        <div className="w-10 h-10 rounded-full bg-danger/15 flex items-center justify-center">
          <AlertCircle className="w-5 h-5 text-danger" />
        </div>
        <div>
          <h3 className="text-sm font-semibold text-text-primary">{title}</h3>
          {message && <p className="text-xs text-text-muted mt-1">{message}</p>}
        </div>
        {onRetry && <Button variant="secondary" size="sm" onClick={onRetry}>{retryLabel}</Button>}
      </div>
    </Card>
  );
}

/* ── Wave 2: Modal, Tabs, ProgressBar, Tooltip (#513) ── */

export function Modal({ open, onClose, title, children, className = '' }) {
  const overlayRef = React.useRef(null);
  const contentRef = React.useRef(null);

  React.useEffect(() => {
    if (!open) return;
    const prev = document.activeElement;
    contentRef.current?.focus();
    const handleKey = (e) => { if (e.key === 'Escape') onClose?.(); };
    document.addEventListener('keydown', handleKey);
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', handleKey);
      document.body.style.overflow = '';
      prev?.focus?.();
    };
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div ref={overlayRef} className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in" onClick={(e) => { if (e.target === overlayRef.current) onClose?.(); }}>
      <div ref={contentRef} role="dialog" aria-modal="true" aria-labelledby={title ? 'modal-title' : undefined} tabIndex={-1} className={`w-full max-w-lg mx-4 bg-surface border border-border rounded-2xl shadow-2xl animate-scale-in focus:outline-none ${className}`}>
        {title && (
          <div className="flex items-center justify-between px-6 pt-5 pb-0">
            <h2 id="modal-title" className="text-lg font-bold text-text-primary">{title}</h2>
            <button onClick={onClose} className="p-1 rounded-lg hover:bg-secondary transition-colors cursor-pointer" aria-label="Close"><span className="text-text-muted text-lg">&times;</span></button>
          </div>
        )}
        <div className="px-6 py-5">{children}</div>
      </div>
    </div>
  );
}

export function Tabs({ tabs, activeTab, onChange, className = '' }) {
  return (
    <div className={`flex flex-col ${className}`}>
      <div className="flex border-b border-border overflow-x-auto" role="tablist">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            role="tab"
            aria-selected={activeTab === tab.id}
            aria-controls={`tabpanel-${tab.id}`}
            onClick={() => onChange(tab.id)}
            className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium whitespace-nowrap border-b-2 transition-all duration-200 cursor-pointer ${
              activeTab === tab.id
                ? 'border-cta text-cta bg-cta/5'
                : 'border-transparent text-text-secondary hover:text-text-primary hover:border-border-light'
            }`}
          >
            {tab.icon && <tab.icon className="w-4 h-4" />}
            {tab.label}
            {tab.badge && <span className="ml-1 px-1.5 py-0.5 text-[10px] font-semibold rounded-full bg-cta/15 text-cta">{tab.badge}</span>}
          </button>
        ))}
      </div>
      {tabs.map((tab) => (
        <div key={tab.id} id={`tabpanel-${tab.id}`} role="tabpanel" aria-labelledby={tab.id} className={activeTab === tab.id ? 'pt-4' : 'hidden'}>
          {activeTab === tab.id && tab.content}
        </div>
      ))}
    </div>
  );
}

export function ProgressBar({ value = 0, max = 100, label, size = 'md', variant = 'default', className = '' }) {
  const pct = Math.min(100, Math.max(0, (value / max) * 100));
  const heights = { sm: 'h-1', md: 'h-2', lg: 'h-3' };
  const colors = { default: 'bg-cta', warning: 'bg-warning', danger: 'bg-danger', info: 'bg-info' };
  return (
    <div className={`flex flex-col gap-1 ${className}`}>
      {label && (
        <div className="flex items-center justify-between text-xs">
          <span className="text-text-secondary">{label}</span>
          <span className="text-text-muted font-mono">{Math.round(pct)}%</span>
        </div>
      )}
      <div className={`w-full ${heights[size]} bg-secondary rounded-full overflow-hidden`} role="progressbar" aria-valuenow={value} aria-valuemin={0} aria-valuemax={max}>
        <div className={`${heights[size]} ${colors[variant]} rounded-full transition-all duration-500 ease-out`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function Tooltip({ children, content, position = 'top' }) {
  const [show, setShow] = React.useState(false);
  const positions = {
    top: 'bottom-full left-1/2 -translate-x-1/2 mb-2',
    bottom: 'top-full left-1/2 -translate-x-1/2 mt-2',
    left: 'right-full top-1/2 -translate-y-1/2 mr-2',
    right: 'left-full top-1/2 -translate-y-1/2 ml-2',
  };
  return (
    <div className="relative inline-flex" onMouseEnter={() => setShow(true)} onMouseLeave={() => setShow(false)} onFocus={() => setShow(true)} onBlur={() => setShow(false)}>
      {children}
      {show && content && (
        <div role="tooltip" className={`absolute z-50 px-2.5 py-1.5 text-xs font-medium text-text-primary bg-secondary border border-border rounded-lg shadow-lg whitespace-nowrap animate-scale-in pointer-events-none ${positions[position]}`}>
          {content}
        </div>
      )}
    </div>
  );
}
