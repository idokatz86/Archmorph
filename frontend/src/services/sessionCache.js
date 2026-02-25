/**
 * sessionCache.js — Persist diagram analysis in sessionStorage so the
 * frontend can transparently restore sessions when the backend restarts
 * and the in-memory store is wiped.
 *
 * Extended to also cache IaC code and HLD data in session (#263).
 */

const CACHE_KEY = 'archmorph_session';

/**
 * Save analysis state to sessionStorage.
 * @param {string} diagramId
 * @param {object} analysis
 * @param {Array}  questions
 * @param {object} answers
 * @param {object} [extra] - Additional data to cache (iacCode, iacFormat, hldData)
 */
export function saveSession(diagramId, analysis, questions = [], answers = {}, extra = {}) {
  try {
    const payload = JSON.stringify({
      diagramId, analysis, questions, answers,
      iacCode: extra.iacCode || null,
      iacFormat: extra.iacFormat || null,
      hldData: extra.hldData || null,
      ts: Date.now(),
    });
    sessionStorage.setItem(CACHE_KEY, payload);
  } catch {
    // sessionStorage full or disabled — non-critical
  }
}

/**
 * Update specific fields in the cached session without overwriting everything.
 * Useful for incrementally caching IaC code or HLD data (#263).
 * @param {object} updates - Fields to merge into the cached session
 */
export function updateSessionCache(updates) {
  try {
    const existing = loadSession();
    if (!existing) return;
    const merged = { ...existing, ...updates, ts: Date.now() };
    sessionStorage.setItem(CACHE_KEY, JSON.stringify(merged));
  } catch {
    // ignored
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
