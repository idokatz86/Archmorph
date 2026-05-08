/**
 * Centralized API client for Archmorph frontend (#170).
 *
 * - Single place for base URL, headers, error handling
 * - Returns parsed JSON or throws with a structured error
 * - Retry with exponential backoff for transient failures (#268)
 * - Configurable request timeout (#268)
 * - User-friendly error messages (#305)
 * - All fetch() calls across the app should migrate here over time
 */

import { API_BASE } from '../constants';

/** Default request timeout in ms */
const DEFAULT_TIMEOUT_MS = 30_000;

/** Max retry attempts for retryable errors */
const MAX_RETRIES = 3;

/** Base delay for exponential backoff (ms) */
const BACKOFF_BASE_MS = process.env.NODE_ENV === 'test' ? 10 : 1000;

/** HTTP status codes that are safe to retry */
const RETRYABLE_STATUS_CODES = new Set([408, 429, 500, 502, 503, 504]);
const TOKEN_KEY = 'archmorph_session_token';

/**
 * Map raw API errors to user-friendly messages (#305).
 * Falls back to the raw message if no mapping exists.
 */
const USER_FRIENDLY_ERRORS = {
  401: 'Your session has expired. Please sign in again.',
  403: 'You don\u2019t have permission to perform this action.',
  404: 'The requested resource was not found. It may have expired.',
  408: 'The request timed out. Please try again.',
  413: 'The uploaded file is too large. Please use a smaller file.',
  429: 'Too many requests. Please wait a moment and try again.',
  500: 'Something went wrong on our end. Please try again shortly.',
  502: 'The service is temporarily unavailable. Please try again.',
  503: 'The service is undergoing maintenance. Please try again later.',
  504: 'The request took too long. Please try again.',
};

class ApiError extends Error {
  constructor(status, body) {
    const rawMsg = body?.error?.message || body?.detail || `HTTP ${status}`;
    const friendlyMsg = USER_FRIENDLY_ERRORS[status] || rawMsg;
    super(friendlyMsg);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
    this.rawMessage = rawMsg;
    this.correlationId = body?.error?.correlation_id || null;
    this.retryable = RETRYABLE_STATUS_CODES.has(status);
  }
}

/**
 * Sleep for a given number of milliseconds.
 */
function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function getStoredToken() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

function isApiRequest(path, url) {
  if (!path.startsWith('http')) return true;

  try {
    const origin = typeof window !== 'undefined' && window.location?.origin ? window.location.origin : 'http://localhost';
    const requestUrl = new URL(url, origin);
    const apiUrl = new URL(API_BASE, origin);
    const apiPath = apiUrl.pathname.replace(/\/$/, '');
    return requestUrl.origin === apiUrl.origin && requestUrl.pathname.startsWith(apiPath || '/');
  } catch {
    return false;
  }
}

function buildHeaders(optionsHeaders = {}, includeDefaultAuth = true) {
  const headers = { ...optionsHeaders };
  const hasAuthorization = Object.keys(headers).some(key => key.toLowerCase() === 'authorization');
  const token = getStoredToken();
  if (includeDefaultAuth && token && !hasAuthorization) {
    headers.Authorization = `Bearer ${token}`;
  }
  return headers;
}

/**
 * Internal fetch wrapper with timeout, retry, and backoff (#268).
 * @param {string} path - API path (appended to API_BASE)
 * @param {RequestInit} options - fetch options
 * @param {AbortSignal} [signal] - optional abort signal
 * @returns {Promise<any>} parsed JSON response
 */
async function request(path, options = {}, signal) {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`;
  const includeDefaultCredentials = isApiRequest(path, url);

  const headers = buildHeaders(options.headers, includeDefaultCredentials);
  // Auto-set JSON content type for non-FormData bodies
  if (options.body && !(options.body instanceof FormData)) {
    headers['Content-Type'] = headers['Content-Type'] || 'application/json';
  }

  let lastError;
  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    // Create a timeout controller that chains with the caller's signal
    const timeoutController = new AbortController();
    const msTimeout = options.timeout !== undefined ? options.timeout : DEFAULT_TIMEOUT_MS;
    const timeoutId = msTimeout > 0 ? setTimeout(() => timeoutController.abort(), msTimeout) : null;

    // If the caller provided a signal, abort our controller when it fires
    const onCallerAbort = () => timeoutController.abort();
    if (signal) {
      if (signal.aborted) {
        clearTimeout(timeoutId);
        throw new DOMException('The operation was aborted.', 'AbortError');
      }
      signal.addEventListener('abort', onCallerAbort, { once: true });
    }

    try {
      const requestOptions = {
        ...options,
        headers,
        signal: timeoutController.signal,
      };
      if (options.credentials !== undefined) {
        requestOptions.credentials = options.credentials;
      } else if (includeDefaultCredentials) {
        requestOptions.credentials = 'include';
      }

      const res = await fetch(url, requestOptions);

      clearTimeout(timeoutId);
      if (signal) signal.removeEventListener('abort', onCallerAbort);

      // No-content responses
      if (res.status === 204) return null;

      const contentType = res.headers.get('content-type') || '';

      // Non-JSON responses (binary exports)
      if (!contentType.includes('application/json')) {
        if (!res.ok) throw new ApiError(res.status, { detail: res.statusText });
        return res;
      }

      const body = await res.json();
      if (!res.ok) {
        const err = new ApiError(res.status, body);
        // Only retry on retryable status codes and if we have attempts left
        if (err.retryable && attempt < MAX_RETRIES) {
          lastError = err;
          const delay = BACKOFF_BASE_MS * Math.pow(2, attempt) + Math.random() * 500;
          await sleep(delay);
          continue;
        }
        throw err;
      }
      return body;
    } catch (err) {
      clearTimeout(timeoutId);
      if (signal) signal.removeEventListener('abort', onCallerAbort);

      // Don't retry user-initiated aborts
      if (err.name === 'AbortError') {
        if (signal?.aborted) throw err; // caller aborted
        // Timeout — wrap as a retryable ApiError
        const timeoutErr = new ApiError(408, { detail: 'Request timed out' });
        if (attempt < MAX_RETRIES) {
          lastError = timeoutErr;
          const delay = BACKOFF_BASE_MS * Math.pow(2, attempt) + Math.random() * 500;
          await sleep(delay);
          continue;
        }
        throw timeoutErr;
      }

      // Network errors are retryable
      if (err instanceof TypeError) {
        lastError = new ApiError(0, { detail: 'Network error \u2014 check your connection.' });
        if (attempt < MAX_RETRIES) {
          const delay = BACKOFF_BASE_MS * Math.pow(2, attempt) + Math.random() * 500;
          await sleep(delay);
          continue;
        }
        throw lastError;
      }

      throw err;
    }
  }
  throw lastError;
}

/** Convenience methods */
const api = {
  get: (path, signal) => request(path, { method: 'GET' }, signal),

  post: (path, body, signal, timeout, headers = {}) =>
    request(
      path,
      {
        method: 'POST',
        body: body instanceof FormData ? body : JSON.stringify(body),
        timeout,
        headers,
      },
      signal
    ),

  patch: (path, body, signal) =>
    request(path, { method: 'PATCH', body: JSON.stringify(body) }, signal),

  delete: (path, signal) => request(path, { method: 'DELETE' }, signal),

  /**
   * Authenticated request (admin endpoints).
   * @param {string} method
   * @param {string} path
   * @param {{ token: string, body?: any, signal?: AbortSignal }} opts
   */
  auth: (method, path, { token, body, signal } = {}) =>
    request(
      path,
      {
        method,
        headers: { Authorization: `Bearer ${token}` },
        body: body ? JSON.stringify(body) : undefined,
      },
      signal,
    ),
};

export { api as default, ApiError };
