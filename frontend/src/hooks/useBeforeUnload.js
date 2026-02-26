import { useEffect } from 'react';

/**
 * Warn users before closing/navigating away when there's unsaved work (#312).
 *
 * Usage:
 *   useBeforeUnload(hasUnsavedChanges);
 *
 * @param {boolean} shouldWarn - Whether to show the browser's native "Leave page?" dialog.
 */
export default function useBeforeUnload(shouldWarn) {
  useEffect(() => {
    if (!shouldWarn) return;

    const handler = (e) => {
      e.preventDefault();
      // Modern browsers ignore custom messages but still show a generic dialog
      e.returnValue = 'You have unsaved work. Are you sure you want to leave?';
      return e.returnValue;
    };

    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [shouldWarn]);
}
