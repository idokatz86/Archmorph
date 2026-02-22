import { useEffect, useRef } from 'react';

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Custom hook that traps keyboard focus inside a container element.
 * Returns a ref to attach to the modal/dialog container.
 *
 * - Moves focus to the first focusable element on mount.
 * - Wraps Tab / Shift+Tab at the boundaries.
 * - Restores focus to the previously focused element on unmount.
 *
 * @param {boolean} active — whether the trap is active (default: true)
 * @returns {React.RefObject}
 */
export default function useFocusTrap(active = true) {
  const containerRef = useRef(null);
  const previousFocus = useRef(null);

  useEffect(() => {
    if (!active) return;

    // Remember the element that had focus before the modal opened
    previousFocus.current = document.activeElement;

    const container = containerRef.current;
    if (!container) return;

    // Move focus into the modal
    const focusFirst = () => {
      const first = container.querySelector(FOCUSABLE);
      if (first) first.focus();
    };
    // Small delay to ensure the DOM is painted
    const raf = requestAnimationFrame(focusFirst);

    const handleKeyDown = (e) => {
      if (e.key !== 'Tab') return;

      const focusable = [...container.querySelectorAll(FOCUSABLE)];
      if (focusable.length === 0) return;

      const first = focusable[0];
      const last = focusable[focusable.length - 1];

      if (e.shiftKey) {
        if (document.activeElement === first) {
          e.preventDefault();
          last.focus();
        }
      } else {
        if (document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };

    container.addEventListener('keydown', handleKeyDown);

    return () => {
      cancelAnimationFrame(raf);
      container.removeEventListener('keydown', handleKeyDown);
      // Restore focus
      if (previousFocus.current && typeof previousFocus.current.focus === 'function') {
        previousFocus.current.focus();
      }
    };
  }, [active]);

  return containerRef;
}
