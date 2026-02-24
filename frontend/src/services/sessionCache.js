/**
 * sessionCache.js — Persist diagram analysis in sessionStorage so the
 * frontend can transparently restore sessions when the backend restarts
 * and the in-memory store is wiped.
 */

const CACHE_KEY = 'archmorph_session';

/**
 * Save analysis state to sessionStorage.
 * @param {string} diagramId
 * @param {object} analysis
 * @param {Array}  questions
 * @param {object} answers
 */
export function saveSession(diagramId, analysis, questions = [], answers = {}) {
  try {
    const payload = JSON.stringify({ diagramId, analysis, questions, answers, ts: Date.now() });
    sessionStorage.setItem(CACHE_KEY, payload);
  } catch {
    // sessionStorage full or disabled — non-critical
  }
}

/**
 * Load cached session from sessionStorage.
 * Returns null if nothing is cached or if the cache is stale (> 2 hours).
 */
export function loadSession() {
  try {
    const raw = sessionStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw);
    // Discard caches older than 2 hours (matches backend TTL)
    if (Date.now() - data.ts > 2 * 60 * 60 * 1000) {
      sessionStorage.removeItem(CACHE_KEY);
      return null;
    }
    return data;
  } catch {
    return null;
  }
}

/** Clear the cached session. */
export function clearSession() {
  try {
    sessionStorage.removeItem(CACHE_KEY);
  } catch {
    // ignored
  }
}
