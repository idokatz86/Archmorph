let reporter = null;

function normalizeError(error) {
  if (error instanceof Error) return error;
  if (typeof error === 'string') return new Error(error);
  return new Error('Unknown frontend error');
}

export function setErrorReporter(fn) {
  reporter = typeof fn === 'function' ? fn : null;
}

export function reportError(error, context = 'frontend', metadata = {}) {
  const normalized = normalizeError(error);
  const payload = { context, metadata };

  if (reporter) {
    reporter(normalized, payload);
    return;
  }

  if (typeof window !== 'undefined' && window.appInsights?.trackException) {
    window.appInsights.trackException({ exception: normalized, properties: payload });
    return;
  }

  if (process.env.NODE_ENV !== 'production') {
    console.error('[Archmorph]', context, normalized, metadata);
  }
}

export function clearErrorReporter() {
  reporter = null;
}