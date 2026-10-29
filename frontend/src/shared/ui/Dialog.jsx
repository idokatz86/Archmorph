import React, { createContext, useContext, useEffect, useId } from 'react';
import { createPortal } from 'react-dom';
import useFocusTrap from '../../hooks/useFocusTrap';

const DialogContext = createContext(null);

export function Dialog({
  open,
  onClose,
  children,
  className = '',
  containerClassName = '',
  backdropClassName = '',
  backdropTestId,
  closeOnBackdrop = true,
  closeOnEscape = true,
  'aria-label': ariaLabel,
}) {
  const titleId = useId();
  const trapRef = useFocusTrap(open);

  useEffect(() => {
    if (!open) return undefined;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    const handleKeyDown = (event) => {
      if (closeOnEscape && event.key === 'Escape' && !event.defaultPrevented) {
        onClose?.();
      }
    };
    document.addEventListener('keydown', handleKeyDown);

    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [closeOnEscape, onClose, open]);

  if (!open) return null;

  return createPortal(
    <DialogContext.Provider value={{ titleId }}>
      <div className={containerClassName}>
        <div
          aria-hidden="true"
          className={backdropClassName}
          data-testid={backdropTestId}
          onClick={closeOnBackdrop ? onClose : undefined}
        />
        <div
          ref={trapRef}
          role="dialog"
          aria-modal="true"
          aria-label={ariaLabel}
          aria-labelledby={ariaLabel ? undefined : titleId}
          tabIndex={-1}
          className={className}
        >
          {children}
        </div>
      </div>
    </DialogContext.Provider>,
    document.body,
  );
}

export function DialogTitle({ as: Component = 'h2', className = '', children }) {
  const context = useContext(DialogContext);
  if (!context) {
    throw new Error('DialogTitle must be rendered inside Dialog');
  }

  return (
    <Component id={context.titleId} className={className}>
      {children}
    </Component>
  );
}
