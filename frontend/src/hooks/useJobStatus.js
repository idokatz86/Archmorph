import { useState, useCallback, useRef, useEffect } from 'react';
import { API_BASE } from '../constants';

/**
 * Hook for polling job status as a fallback when SSE is unavailable.
 *
 * Usage:
 *   const { status, progress, result, error, poll, cancel, stop } = useJobStatus();
 *   // After starting a job:
 *   poll(jobId);
 *
 * @returns {{ status, progress, message, result, error, loading, poll, cancel, stop }}
 */
export default function useJobStatus() {
  const [status, setStatus] = useState(null);
  const [progress, setProgress] = useState(0);
  const [message, setMessage] = useState('');
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const timeoutRef = useRef(null);
  const stoppedRef = useRef(false);

  // Clear any pending timeout on unmount
  useEffect(() => {
    return () => {
      stoppedRef.current = true;
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
      }
    };
  }, []);

  const stop = useCallback(() => {
    stoppedRef.current = true;
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
    setLoading(false);
  }, []);

  const poll = useCallback(async (jobId, interval = 2000) => {
    if (!jobId) return;

    stoppedRef.current = false;
    setLoading(true);
    setError(null);
    setResult(null);
    setStatus('queued');

    const tick = async () => {
      if (stoppedRef.current) return;
      try {
        const res = await fetch(`${API_BASE}/jobs/${jobId}`);
        if (stoppedRef.current) return;
        if (!res.ok) throw new Error(`Job status request failed (${res.status})`);
        const data = await res.json();

        if (stoppedRef.current) return;

        setStatus(data.status);
        setProgress(data.progress ?? 0);
        setMessage(data.progress_message ?? '');

        if (data.status === 'completed') {
          setResult(data.result);
          setLoading(false);
          return; // stop polling
        }

        if (data.status === 'failed') {
          setError(data.error || 'Job failed');
          setLoading(false);
          return;
        }

        if (data.status === 'cancelled') {
          setError('Job was cancelled');
          setLoading(false);
          return;
        }

        // Still running — schedule next poll (tracked via ref)
        timeoutRef.current = setTimeout(tick, interval);
      } catch (err) {
        if (!stoppedRef.current) {
          setError(err.message);
          setLoading(false);
        }
      }
    };

    tick();
  }, []);

  const cancel = useCallback(async (jobId) => {
    if (!jobId) return;
    stop();
    try {
      await fetch(`${API_BASE}/jobs/${jobId}/cancel`, { method: 'POST' });
      setStatus('cancelled');
      setLoading(false);
    } catch (err) {
      setError(err.message);
    }
  }, [stop]);

  return { status, progress, message, result, error, loading, poll, cancel, stop };
}
