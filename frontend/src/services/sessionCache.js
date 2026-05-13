/**
 * sessionCache.js — Optional diagram analysis persistence in sessionStorage
 * for restore flows when the backend in-memory store is wiped.
 * Sensitive payloads are not cached by default (confidential mode).
 *
 * Extended to also cache IaC code and HLD data in session (#263).
 * Multi-tab safe: each diagram gets its own cache key (#265).
 */

const CACHE_PREFIX = 'archmorph_session_';
const LEGACY_CACHE_KEY = 'archmorph_session';
const SENSITIVE_CACHE_OPT_IN_KEY = 'archmorph_sensitive_cache_opt_in';

function _isTrue(value) {
  return ['true', '1', 'yes', 'on'].includes(String(value || '').toLowerCase());
}

function _isSensitiveCacheOptedIn() {
  try {
    const envEnabled = _isTrue(import.meta?.env?.VITE_ENABLE_SENSITIVE_SESSION_CACHE);
    if (envEnabled) return true;
  } catch { /* ignore */ }
  try {
    const storageOptIn = sessionStorage.getItem(SENSITIVE_CACHE_OPT_IN_KEY);
    return _isTrue(storageOptIn);
  } catch {
    return false;
  }
}

export function shouldPersistSensitiveSessionCache(options = {}) {
  if (options.persistSensitive === true) return true;
  if (options.persistSensitive === false) return false;
  return _isSensitiveCacheOptedIn();
}

function _sanitizeAnalysis(analysis) {
  if (!analysis || typeof analysis !== 'object') return analysis;
  const sanitized = { ...analysis };
  delete sanitized.export_capability;
  return sanitized;
}

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
 * @param {object} [extra] - Additional data to cache (iacCode, iacFormat, hldData, persistSensitive)
 */
export function saveSession(diagramId, analysis, questions = [], answers = {}, extra = {}) {
  if (!shouldPersistSensitiveSessionCache(extra)) return;
  try {
    const payload = JSON.stringify({
      diagramId, analysis: _sanitizeAnalysis(analysis), questions, answers,
      allQuestions: extra.allQuestions || [],
      questionAssumptions: extra.questionAssumptions || [],
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
    const sanitizedUpdates = { ...updates };
    delete sanitizedUpdates.exportCapability;
    if (Object.prototype.hasOwnProperty.call(sanitizedUpdates, 'analysis')) {
      sanitizedUpdates.analysis = _sanitizeAnalysis(sanitizedUpdates.analysis);
    }
    const merged = { ...existing, ...sanitizedUpdates, ts: Date.now() };
    delete merged.exportCapability;
    merged.analysis = _sanitizeAnalysis(merged.analysis);
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
    delete data.exportCapability;
    data.analysis = _sanitizeAnalysis(data.analysis);
    return data;
  } catch {
    return null;
  }
}

/** Clear the cached session for a specific diagram or the active one. */
export function clearSession(diagramId) {
  try {
    const id = diagramId || _getActiveDiagram();
    if (id) {
      sessionStorage.removeItem(_cacheKey(id));
      sessionStorage.removeItem(`archmorph_img_${id}`);
    }
    sessionStorage.removeItem(LEGACY_CACHE_KEY);
    sessionStorage.removeItem('archmorph_active_diagram');
  } catch {
    // ignored
  }
}

/**
 * Cache the uploaded diagram image for session restore (#333).
 * Only images under 1 MB (base64) are cached to avoid exceeding the
 * sessionStorage quota.
 */
export function cacheImage(diagramId, base64, contentType, options = {}) {
  if (!shouldPersistSensitiveSessionCache(options)) return;
  try {
    if (!base64 || base64.length > 1_400_000) return; // ~1 MB limit
    sessionStorage.setItem(`archmorph_img_${diagramId}`, JSON.stringify({ base64, contentType }));
  } catch { /* quota exceeded — non-critical */ }
}

/** Retrieve cached image data for session restore (#333). */
export function loadCachedImage(diagramId, options = {}) {
  if (!shouldPersistSensitiveSessionCache(options)) return null;
  try {
    const raw = sessionStorage.getItem(`archmorph_img_${diagramId}`);
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}
