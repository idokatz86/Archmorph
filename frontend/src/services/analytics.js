/**
 * Product Analytics — Funnel tracking (#492).
 *
 * Lightweight event tracking layer that:
 * 1. Sends events to backend /api/analytics/events endpoint
 * 2. Supports PostHog/Mixpanel integration when configured
 * 3. Tracks the core PLG funnel: sign_up → first_upload → analysis_complete →
 *    iac_generated → iac_downloaded → upgrade_to_pro
 *
 * Usage:
 *   import { track, trackFunnel } from '../services/analytics';
 *   track('diagram_uploaded', { format: 'png', size_kb: 1024 });
 *   trackFunnel('analysis_complete', { service_count: 12 });
 */

const API_BASE = import.meta.env.VITE_API_BASE || '/api';
const POSTHOG_KEY = import.meta.env.VITE_POSTHOG_KEY || '';
const ANALYTICS_ENABLED = import.meta.env.VITE_ANALYTICS_ENABLED !== 'false';

// Session ID for anonymous tracking
let _sessionId = null;
function getSessionId() {
  if (_sessionId) return _sessionId;
  _sessionId = sessionStorage.getItem('archmorph-session-id');
  if (!_sessionId) {
    _sessionId = crypto.randomUUID();
    sessionStorage.setItem('archmorph-session-id', _sessionId);
  }
  return _sessionId;
}

// PostHog initialization (lazy, only if key provided)
let _posthog = null;
async function getPostHog() {
  if (_posthog) return _posthog;
  if (!POSTHOG_KEY) return null;
  try {
    const { default: posthog } = await import('posthog-js');
    posthog.init(POSTHOG_KEY, {
      api_host: import.meta.env.VITE_POSTHOG_HOST || 'https://app.posthog.com',
      autocapture: false,
      capture_pageview: false,
      persistence: 'localStorage',
    });
    _posthog = posthog;
    return posthog;
  } catch {
    return null;
  }
}

/**
 * Track a generic event.
 */
export async function track(eventName, properties = {}) {
  if (!ANALYTICS_ENABLED) return;

  const payload = {
    event: eventName,
    session_id: getSessionId(),
    timestamp: new Date().toISOString(),
    properties: {
      ...properties,
      page: window.location.hash || '/',
      referrer: document.referrer || null,
    },
  };

  // Send to backend (fire-and-forget)
  try {
    fetch(`${API_BASE}/analytics/events`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      keepalive: true,
    }).catch(() => {}); // Silently fail
  } catch {
    // No-op
  }

  // PostHog (if configured)
  const ph = await getPostHog();
  if (ph) {
    ph.capture(eventName, payload.properties);
  }
}

/**
 * Funnel steps — ordered conversion events.
 */
const FUNNEL_STEPS = [
  'page_view',
  'sign_up',
  'first_upload',
  'analysis_complete',
  'questions_answered',
  'iac_generated',
  'iac_downloaded',
  'hld_exported',
  'cost_viewed',
  'upgrade_to_pro',
];

/**
 * Track a funnel step (automatically includes step index for ordering).
 */
export function trackFunnel(step, properties = {}) {
  const stepIndex = FUNNEL_STEPS.indexOf(step);
  track(`funnel:${step}`, {
    ...properties,
    funnel_step: step,
    funnel_index: stepIndex >= 0 ? stepIndex : -1,
  });
}

/**
 * Track page view (call on tab change).
 */
export function trackPageView(tabName) {
  track('page_view', { tab: tabName });
}

/**
 * Identify user (call after auth).
 */
export async function identify(userId, traits = {}) {
  if (!ANALYTICS_ENABLED) return;

  try {
    const ph = await getPostHog();
    if (ph) {
      ph.identify(userId, traits);
    }
  } catch {
    // No-op
  }

  track('user_identified', { user_id: userId, ...traits });
}

/**
 * Track feature adoption.
 */
export function trackFeature(featureName, properties = {}) {
  track(`feature:${featureName}`, properties);
}
