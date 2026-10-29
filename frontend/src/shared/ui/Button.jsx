import React, { forwardRef } from 'react';
import { Loader2 } from 'lucide-react';

export const Button = forwardRef(function Button(
  {
    children,
    onClick,
    variant = 'primary',
    size = 'md',
    disabled = false,
    busy = false,
    loading = false,
    icon: Icon,
    className = '',
    type = 'button',
    'aria-label': ariaLabel,
    ...rest
  },
  ref,
) {
  const isBusy = busy || loading;
  const base = 'inline-flex items-center justify-center gap-2 font-semibold rounded-lg transition-all duration-200 cursor-pointer select-none disabled:opacity-40 disabled:cursor-not-allowed active:scale-[0.97] focus:outline-none focus:ring-2 focus:ring-cta/50';
  const variants = {
    primary: 'bg-cta hover:bg-cta-hover text-surface shadow-lg shadow-cta/20',
    secondary: 'bg-secondary hover:bg-border-light text-text-primary border border-border',
    ghost: 'hover:bg-secondary text-text-secondary hover:text-text-primary',
    danger: 'bg-danger/15 hover:bg-danger/25 text-danger border border-danger/30',
  };
  const sizes = {
    sm: 'px-3 py-1.5 text-xs',
    md: 'px-4 py-2 text-sm',
    lg: 'px-6 py-3 text-base',
  };

  return (
    <button
      {...rest}
      ref={ref}
      type={type}
      onClick={onClick}
      disabled={disabled || isBusy}
      aria-busy={isBusy || undefined}
      aria-label={ariaLabel}
      className={`${base} ${variants[variant] || variants.primary} ${sizes[size] || sizes.md} ${className}`}
    >
      {isBusy ? (
        <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" focusable="false" />
      ) : Icon ? (
        <Icon className="w-4 h-4" aria-hidden="true" focusable="false" />
      ) : null}
      {children}
    </button>
  );
});
