import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import useSSE from '../../hooks/useSSE';
import useJobStatus from '../../hooks/useJobStatus';

// ─────────────────────────────────────────────────────────────
// Mock EventSource
// ─────────────────────────────────────────────────────────────
class MockEventSource {
  constructor(url) {
    this.url = url;
    this.readyState = 0; // CONNECTING
    this._listeners = {};
    MockEventSource._instances.push(this);

    // Simulate async open
    setTimeout(() => {
      this.readyState = 1; // OPEN
      if (this.onopen) this.onopen();
    }, 0);
  }
  addEventListener(type, handler) {
    if (!this._listeners[type]) this._listeners[type] = [];
    this._listeners[type].push(handler);
  }
  removeEventListener(type, handler) {
    if (this._listeners[type]) {
      this._listeners[type] = this._listeners[type].filter(h => h !== handler);
    }
  }
  close() {
    this.readyState = 2; // CLOSED
  }
  // Test helper: emit a named event
  _emit(type, data) {
    const event = { data: typeof data === 'string' ? data : JSON.stringify(data) };
    if (this._listeners[type]) {
      this._listeners[type].forEach(h => h(event));
    }
  }
}
MockEventSource._instances = [];

// ─────────────────────────────────────────────────────────────
// useSSE tests
// ─────────────────────────────────────────────────────────────

describe('useSSE', () => {
  beforeEach(() => {
    MockEventSource._instances = [];
    global.EventSource = MockEventSource;
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    delete global.EventSource;
  });

  it('returns disconnected state when jobId is null', () => {
    const { result } = renderHook(() => useSSE(null));
    expect(result.current.connected).toBe(false);
    expect(result.current.error).toBeNull();
    expect(MockEventSource._instances).toHaveLength(0);
  });

  it('connects when jobId is provided', async () => {
    const { result } = renderHook(() =>
      useSSE('job-1', { onProgress: vi.fn(), onComplete: vi.fn(), onError: vi.fn() })
    );
    expect(MockEventSource._instances).toHaveLength(1);
    expect(MockEventSource._instances[0].url).toContain('job-1');

    // Simulate open
    await act(async () => { vi.advanceTimersByTime(10); });
    expect(result.current.connected).toBe(true);
  });

  it('calls onProgress when progress event received', async () => {
    const onProgress = vi.fn();
    renderHook(() => useSSE('job-2', { onProgress, onComplete: vi.fn(), onError: vi.fn() }));

    await act(async () => { vi.advanceTimersByTime(10); });
    const es = MockEventSource._instances[0];

    act(() => {
      es._emit('progress', { progress: 50, message: 'Halfway' });
    });

    expect(onProgress).toHaveBeenCalledWith({ progress: 50, message: 'Halfway' });
  });

  it('calls onComplete and closes on complete event', async () => {
    const onComplete = vi.fn();
    const { result } = renderHook(() =>
      useSSE('job-3', { onProgress: vi.fn(), onComplete, onError: vi.fn() })
    );

    await act(async () => { vi.advanceTimersByTime(10); });
    const es = MockEventSource._instances[0];

    act(() => {
      es._emit('complete', { result: { data: 'done' } });
    });

    expect(onComplete).toHaveBeenCalledWith({ data: 'done' });
    expect(es.readyState).toBe(2); // CLOSED
  });

  it('calls onError on error event', async () => {
    const onError = vi.fn();
    renderHook(() => useSSE('job-4', { onProgress: vi.fn(), onComplete: vi.fn(), onError }));

    await act(async () => { vi.advanceTimersByTime(10); });
    const es = MockEventSource._instances[0];

    act(() => {
      es._emit('error', { error: 'Something failed' });
    });

    expect(onError).toHaveBeenCalledWith('Something failed');
  });

  it('closes EventSource on unmount', async () => {
    const { unmount } = renderHook(() =>
      useSSE('job-5', { onProgress: vi.fn(), onComplete: vi.fn(), onError: vi.fn() })
    );

    await act(async () => { vi.advanceTimersByTime(10); });
    const es = MockEventSource._instances[0];

    unmount();
    expect(es.readyState).toBe(2); // CLOSED
  });

  it('close() manually disconnects', async () => {
    const { result } = renderHook(() =>
      useSSE('job-6', { onProgress: vi.fn(), onComplete: vi.fn(), onError: vi.fn() })
    );

    await act(async () => { vi.advanceTimersByTime(10); });

    act(() => { result.current.close(); });
    expect(result.current.connected).toBe(false);
  });
});

// ─────────────────────────────────────────────────────────────
// useJobStatus tests
// ─────────────────────────────────────────────────────────────

describe('useJobStatus', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('starts with null status', () => {
    const { result } = renderHook(() => useJobStatus());
    expect(result.current.status).toBeNull();
    expect(result.current.loading).toBe(false);
  });

  it('polls and updates status on completion', async () => {
    fetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ status: 'completed', progress: 100, result: { x: 1 } }),
    });

    const { result } = renderHook(() => useJobStatus());

    await act(async () => {
      result.current.poll('job-poll-1');
      await vi.advanceTimersByTimeAsync(100);
    });

    expect(result.current.status).toBe('completed');
    expect(result.current.result).toEqual({ x: 1 });
    expect(result.current.loading).toBe(false);
  });

  it('sets error on failure status', async () => {
    fetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ status: 'failed', error: 'Boom' }),
    });

    const { result } = renderHook(() => useJobStatus());

    await act(async () => {
      result.current.poll('job-poll-2');
      await vi.advanceTimersByTimeAsync(100);
    });

    expect(result.current.status).toBe('failed');
    expect(result.current.error).toBe('Boom');
  });

  it('cancel sends POST and updates status', async () => {
    fetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({}) });

    const { result } = renderHook(() => useJobStatus());

    await act(async () => {
      await result.current.cancel('job-cancel-1');
    });

    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/jobs/job-cancel-1/cancel'),
      expect.objectContaining({ method: 'POST' })
    );
    expect(result.current.status).toBe('cancelled');
  });
});
