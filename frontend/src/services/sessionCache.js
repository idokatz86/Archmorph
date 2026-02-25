/**
 * sessionCache.js — Persist diagram analysis in sessionStorage so the
 * frontend can transparently restore sessions when the backend restarts
 * and the in-memory store is wiped.
 *
 * Extended to also cache IaC code and HLD data in session (#263).
 * Multi-tab safe: each diagram gets its own cache key (#265).
 */

const CACHE_PREFIX = 'archmorph_session_';
const LEGACY_CACHE_KEY = 'archmorph_session';

/** Build a per-diagram cache key (#265 — multi-tab data loss fix). */
function _cacheKey(diagramId) {
  return diagramId ? `${CACHE_PREFIX}${diagramId}` : LEGACY_CACHE_KEY;
}

/** Track the most recently used diagram id for loadSession() fallback. */
function _setActiveDiagram(diagramId) {
  if (diagramId) {
    try { sessionStorage.setItem('archmorph_active_diagram', diagramId); } catch { /* ignore */ }
  }
}

function _getActiveDiagram() {
  try { return sessionStorage.getItem('archmorph_active_diagram'); } catch { return null; }
}

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
    sessionStorage.setItem(_cacheKey(diagramId), payload);
    _setActiveDiagram(diagramId);
    // Clean up legacy key if it exists
    try { sessionStorage.removeItem(LEGACY_CACHE_KEY); } catch { /* ignore */ }
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
    sessionStorage.setItem(_cacheKey(existing.diagramId), JSON.stringify(merged));
  } catch {
    // ignored
  }
}

/**
 * Load cached session from sessionStorage.
 * Returns null if nothing is cached or if the cache is stale (> 2 hours).
 * @param {string} [diagramId] - Optional specific diagram to load.
 */
export function loadSession(diagramId) {
  try {
    const id = diagramId || _getActiveDiagram();
    const key = id ? _cacheKey(id) : LEGACY_CACHE_KEY;
    let raw = sessionStorage.getItem(key);
    // Fall back to legacy key for migration (#265)
    if (!raw && key !== LEGACY_CACHE_KEY) {
      raw = sessionStorage.getItem(LEGACY_CACHE_KEY);
    }
    if (!raw) return null;
    const data = JSON.parse(raw);
    // Discard caches older than 2 hours (matches backend TTL)
    if (Date.now() - data.ts > 2 * 60 * 60 * 1000) {
      sessionStorage.removeItem(key);
      return null;
    }
    return data;
  } catch {
    return null;
  }
}

/** Clear the cached session for a specific diagram or the active one. */
export function clearSession(diagramId) {
  try {
    const id = diagramId || _getActiveDiagram();
    if (id) sessionStorage.removeItem(_cacheKey(id));
    sessionStorage.removeItem(LEGACY_CACHE_KEY);
    sessionStorage.removeItem('archmorph_active_diagram');
  } catch {
    // ignored
  }
}
