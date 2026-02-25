/**
 * useSessionExpiry — Warn users before their session expires (#261).
 *
 * Starts a countdown timer when a diagram is uploaded. Shows a
 * warning toast 5 minutes before the session TTL elapses, and fires
 * an onExpired callback when the session is fully expired.
 *
 * Also clears stale error state on new uploads to prevent the
 * "session expired" banner from persisting across workflows (#227).
 */
import { useState, useEffect, useRef, useCallback } from 'react';

/** Backend session TTL in seconds (must match SESSION_STORE ttl) */
const SESSION_TTL_SECONDS = 7200; // 2 hours

/** Warn this many seconds before expiry */
const WARN_BEFORE_SECONDS = 300; // 5 minutes

/**
 * @param {object} opts
 * @param {string|null} opts.diagramId - Active diagram ID (null when idle)
 * @param {function} opts.onExpired   - Called when the session fully expires
 * @returns {{ expiryWarning: string|null, sessionSecondsLeft: number|null, dismissWarning: function }}
 */
export default function useSessionExpiry({ diagramId, onExpired }) {
  const [secondsLeft, setSecondsLeft] = useState(null);
  const [dismissed, setDismissed] = useState(false);
  const startTimeRef = useRef(null);
  const intervalRef = useRef(null);

  // Reset timer when a new diagram is uploaded
  useEffect(() => {
    if (!diagramId) {
      // No active session — clear everything
      setSecondsLeft(null);
      setDismissed(false);
      if (intervalRef.current) clearInterval(intervalRef.current);
      startTimeRef.current = null;
      return;
    }

    // New diagram → fresh timer
    startTimeRef.current = Date.now();
    setDismissed(false);

    intervalRef.current = setInterval(() => {
      const elapsed = Math.floor((Date.now() - startTimeRef.current) / 1000);
      const remaining = SESSION_TTL_SECONDS - elapsed;
      setSecondsLeft(remaining);

      if (remaining <= 0) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
        if (onExpired) onExpired();
      }
    }, 1000);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [diagramId, onExpired]);

  const dismissWarning = useCallback(() => setDismissed(true), []);

  // Build warning message only when close to expiry
  let expiryWarning = null;
  if (secondsLeft !== null && secondsLeft > 0 && secondsLeft <= WARN_BEFORE_SECONDS && !dismissed) {
    const mins = Math.floor(secondsLeft / 60);
    const secs = secondsLeft % 60;
    expiryWarning = `Session expires in ${mins}:${secs.toString().padStart(2, '0')}. Save your work or re-upload to continue.`;
  }

  return {
    expiryWarning,
    sessionSecondsLeft: secondsLeft,
    dismissWarning,
  };
}
