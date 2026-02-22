/**
 * Centralized API client for Archmorph frontend (#170).
 *
 * - Single place for base URL, headers, error handling
 * - Returns parsed JSON or throws with a structured error
 * - All fetch() calls across the app should migrate here over time
 */

import { API_BASE } from '../constants';

class ApiError extends Error {
  constructor(status, body) {
    const msg = body?.error?.message || body?.detail || `HTTP ${status}`;
    super(msg);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
    this.correlationId = body?.error?.correlation_id || null;
  }
}

/**
 * Internal fetch wrapper.
 * @param {string} path - API path (appended to API_BASE)
 * @param {RequestInit} options - fetch options
 * @param {AbortSignal} [signal] - optional abort signal
 * @returns {Promise<any>} parsed JSON response
 */
async function request(path, options = {}, signal) {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`;

  const headers = { ...options.headers };
  // Auto-set JSON content type for non-FormData bodies
  if (options.body && !(options.body instanceof FormData)) {
    headers['Content-Type'] = headers['Content-Type'] || 'application/json';
  }

  const res = await fetch(url, { ...options, headers, signal });

  // No-content responses
  if (res.status === 204) return null;

  const contentType = res.headers.get('content-type') || '';

  // Non-JSON responses (binary exports)
  if (!contentType.includes('application/json')) {
    if (!res.ok) throw new ApiError(res.status, { detail: res.statusText });
    return res;
  }

  const body = await res.json();
  if (!res.ok) throw new ApiError(res.status, body);
  return body;
}

/** Convenience methods */
const api = {
  get: (path, signal) => request(path, { method: 'GET' }, signal),

  post: (path, body, signal) =>
    request(
      path,
      {
        method: 'POST',
        body: body instanceof FormData ? body : JSON.stringify(body),
      },
      signal,
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
