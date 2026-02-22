import { useEffect, useRef, useCallback, useState } from 'react';
import { API_BASE } from '../constants';

/**
 * React hook for consuming Server-Sent Events (SSE) from the jobs API.
 *
 * Connects to `GET /api/jobs/{jobId}/stream` and dispatches events
 * to the provided callback. Automatically reconnects on transient
 * errors (up to `maxRetries`) and cleans up on unmount.
 *
 * @param {string|null} jobId  — Job ID to stream (null = inactive)
 * @param {object}      opts
 * @param {function}    opts.onProgress  — Called with `{ progress, message }` on each progress event
 * @param {function}    opts.onComplete  — Called with the parsed result object
 * @param {function}    opts.onError     — Called with error message string
 * @param {function}    [opts.onStatus]  — Called with status string on status changes
 * @param {number}      [opts.maxRetries=3] — Max reconnection attempts
 * @returns {{ connected: boolean, error: string|null, close: () => void }}
 */
export default function useSSE(jobId, {
  onProgress,
  onComplete,
  onError,
  onStatus,
  maxRetries = 3,
} = {}) {
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState(null);
  const esRef = useRef(null);
  const retriesRef = useRef(0);
  const closedRef = useRef(false);

  // Keep callbacks in refs so reconnect logic always calls latest version
  const cbRef = useRef({ onProgress, onComplete, onError, onStatus });
  cbRef.current = { onProgress, onComplete, onError, onStatus };

  const close = useCallback(() => {
    closedRef.current = true;
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
    setConnected(false);
  }, []);

  useEffect(() => {
    if (!jobId) return;

    closedRef.current = false;
    retriesRef.current = 0;
    setError(null);

    const connect = () => {
      if (closedRef.current) return;

      const url = `${API_BASE}/jobs/${jobId}/stream`;
      const es = new EventSource(url);
      esRef.current = es;

      es.onopen = () => {
        setConnected(true);
        setError(null);
        retriesRef.current = 0;
      };

      // Named event handlers
      es.addEventListener('status', (e) => {
        try {
          const data = JSON.parse(e.data);
          cbRef.current.onStatus?.(data.status);
        } catch { /* ignore parse errors */ }
      });

      es.addEventListener('progress', (e) => {
        try {
          const data = JSON.parse(e.data);
          cbRef.current.onProgress?.(data);
        } catch { /* ignore */ }
      });

      es.addEventListener('complete', (e) => {
        try {
          const data = JSON.parse(e.data);
          cbRef.current.onComplete?.(data.result ?? data);
        } catch { /* ignore */ }
        close();
      });

      es.addEventListener('error', (e) => {
        // SSE "error" event from server (named event, not onerror)
        try {
          const data = JSON.parse(e.data);
          const msg = data.error || data.message || 'Job failed';
          setError(msg);
          cbRef.current.onError?.(msg);
        } catch { /* ignore */ }
        close();
      });

      es.addEventListener('cancelled', () => {
        setError('Job was cancelled');
        cbRef.current.onError?.('Job was cancelled');
        close();
      });

      // Connection-level error (network/timeout)
      es.onerror = () => {
        es.close();
        esRef.current = null;
        setConnected(false);

        if (closedRef.current) return;

        retriesRef.current += 1;
        if (retriesRef.current <= maxRetries) {
          // Exponential backoff: 1s, 2s, 4s
          const delay = Math.min(1000 * Math.pow(2, retriesRef.current - 1), 8000);
          setTimeout(connect, delay);
        } else {
          const msg = 'Connection lost. Please refresh or try again.';
          setError(msg);
          cbRef.current.onError?.(msg);
        }
      };
    };

    connect();

    return () => {
      closedRef.current = true;
      if (esRef.current) {
        esRef.current.close();
        esRef.current = null;
      }
      setConnected(false);
    };
  }, [jobId, maxRetries, close]);

  return { connected, error, close };
}
