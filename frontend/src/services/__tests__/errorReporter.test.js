import { describe, it, expect, vi, afterEach } from 'vitest';
import { clearErrorReporter, reportError, setErrorReporter } from '../errorReporter';

describe('errorReporter', () => {
  afterEach(() => {
    clearErrorReporter();
    vi.restoreAllMocks();
  });

  it('routes normalized errors to the configured reporter', () => {
    const reporter = vi.fn();
    setErrorReporter(reporter);

    reportError('boom', 'test-context', { feature: 'unit' });

    expect(reporter).toHaveBeenCalledTimes(1);
    expect(reporter.mock.calls[0][0]).toBeInstanceOf(Error);
    expect(reporter.mock.calls[0][0].message).toBe('boom');
    expect(reporter.mock.calls[0][1]).toEqual({
      context: 'test-context',
      metadata: { feature: 'unit' },
    });
  });
});