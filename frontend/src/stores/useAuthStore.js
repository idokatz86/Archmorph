/**
 * Auth state store — Zustand (#246).
 *
 * Manages user authentication state:
 * - Checks Azure SWA /.auth/me on mount
 * - Falls back to localStorage session token
 * - Provides login/logout/refresh actions
 */

import { create } from 'zustand';
import { API_BASE } from '../constants';

export const TOKEN_KEY = 'archmorph_session_token';
const REFRESH_KEY = 'archmorph_refresh_token';

/** Read stored token from localStorage */
function getStoredToken() {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}
function getStoredRefresh() {
  try { return localStorage.getItem(REFRESH_KEY); } catch { return null; }
}
function storeTokens(session, refresh) {
  try {
    if (session) localStorage.setItem(TOKEN_KEY, session);
    if (refresh) localStorage.setItem(REFRESH_KEY, refresh);
  } catch { /* private mode */ }
}
function clearTokens() {
  try {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_KEY);
  } catch { /* private mode */ }
}

async function exchangeSwaSession() {
  const response = await fetch('/api/auth/swa-session', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
  });
  if (!response.ok) return null;
  return response.json();
}

async function validateStoredToken(token) {
  if (!token) return null;
  const response = await fetch(`${API_BASE}/auth/me`, {
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
  });
  if (!response.ok) return null;
  const user = await response.json();
  return user?.id ? user : null;
}

const SWA_PROVIDER_MAP = {
  aad: 'microsoft',
  microsoft: 'microsoft',
  google: 'google',
  github: 'github',
};

function claimValue(principal, names) {
  const claims = Array.isArray(principal?.claims) ? principal.claims : [];
  return claims.find((claim) => names.includes(claim.typ))?.val || null;
}

function userFromSwaPrincipal(principal) {
  if (!principal?.userId) return null;
  const roles = Array.isArray(principal.userRoles) ? principal.userRoles : [];
  if (!roles.includes('authenticated')) return null;

  const identityProvider = (principal.identityProvider || 'swa').toLowerCase();
  const provider = SWA_PROVIDER_MAP[identityProvider] || identityProvider;
  const email = claimValue(principal, [
    'http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress',
    'emails',
    'email',
  ]) || principal.userDetails || null;
  const name = claimValue(principal, [
    'name',
    'http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name',
  ]) || principal.userDetails || 'User';

  return {
    id: `${identityProvider}_${principal.userId}`,
    email,
    name,
    avatar_url: claimValue(principal, ['picture']),
    provider,
    tier: 'free',
    tenant_id: 'default_tenant',
    roles: roles.filter((role) => role !== 'anonymous'),
    authenticated: true,
  };
}

export function buildPostLoginRedirectUri(location = window.location) {
  return encodeURIComponent(`${location.pathname}${location.search}${location.hash}`);
}

const useAuthStore = create((set, get) => ({
  // ── State ──
  user: null,
  isAuthenticated: false,
  hasBackendSession: false,
  isLoading: true,
  sessionToken: getStoredToken(),

  ensureBackendSession: async () => {
    const current = get();
    if (current.hasBackendSession && current.sessionToken) return true;

    const storedToken = getStoredToken();
    let tokenValidationIndeterminate = false;
    if (storedToken) {
      try {
        const user = await validateStoredToken(storedToken);
        if (user) {
          set({ user, isAuthenticated: true, hasBackendSession: true, sessionToken: storedToken, isLoading: false });
          return true;
        }
      } catch {
        tokenValidationIndeterminate = true;
      }
    }

    if (!tokenValidationIndeterminate) {
      const refreshed = await current._tryRefresh();
      if (refreshed) return true;
    }

    const exchanged = await exchangeSwaSession().catch(() => null);
    if (exchanged?.user?.id && exchanged.session_token) {
      storeTokens(exchanged.session_token, exchanged.refresh_token);
      set({
        user: exchanged.user,
        isAuthenticated: true,
        hasBackendSession: true,
        sessionToken: exchanged.session_token,
        isLoading: false,
      });
      return true;
    }

    return false;
  },

  // ── Initialize — call on app mount ──
  initialize: async () => {
    set({ isLoading: true });

    // 1. Try Azure SWA built-in auth (production on Static Web Apps)
    try {
      const res = await fetch('/.auth/me', { credentials: 'include' });
      if (res.ok) {
        const data = await res.json();
        const principal = data?.clientPrincipal;
        if (principal?.userId) {
          const swaUser = userFromSwaPrincipal(principal);
          // SWA authenticated — get full user from our API
          const apiRes = await fetch(`${API_BASE}/auth/me`, {
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
          });
          if (apiRes.ok) {
            try {
              const contentType = apiRes.headers?.get?.('content-type') || '';
              const shouldParseJson = !contentType || contentType.includes('application/json');
              const user = shouldParseJson ? await apiRes.json() : null;
              if (user && user.id) {
                set({ user, isAuthenticated: true, hasBackendSession: true, isLoading: false });
                return;
              }
            } catch {
              // Fall back to SWA principal-derived profile when API auth route is misconfigured.
            }
          }
          const token = getStoredToken();
          if (token) {
            let shouldClearStoredToken = false;
            try {
              const user = await validateStoredToken(token);
              if (user) {
                set({ user, isAuthenticated: true, hasBackendSession: true, sessionToken: token, isLoading: false });
                return;
              }
              const tokenRes = await fetch(`${API_BASE}/auth/me`, {
                headers: {
                  'Authorization': `Bearer ${token}`,
                  'Content-Type': 'application/json',
                },
              });
              if (tokenRes.ok) {
                const refreshed = await get()._tryRefresh();
                if (refreshed) return;
                shouldClearStoredToken = true;
              }
              else if (tokenRes.status >= 400 && tokenRes.status < 500) {
                const refreshed = await get()._tryRefresh();
                if (refreshed) return;
                shouldClearStoredToken = true;
              }
            } catch {
              // Preserve the token when validation failed for an indeterminate reason.
            }
            if (shouldClearStoredToken) clearTokens();
          }
          const exchanged = await exchangeSwaSession().catch(() => null);
          if (exchanged?.user?.id && exchanged.session_token) {
            storeTokens(exchanged.session_token, exchanged.refresh_token);
            set({
              user: exchanged.user,
              isAuthenticated: true,
              hasBackendSession: true,
              sessionToken: exchanged.session_token,
              isLoading: false,
            });
            return;
          }
          if (swaUser) {
            set({ user: swaUser, isAuthenticated: true, hasBackendSession: false, isLoading: false, sessionToken: null });
            return;
          }
        }
      }
    } catch {
      // Not running on SWA — expected in dev
    }

    // 2. Try existing session token from localStorage
    const token = getStoredToken();
    if (token) {
      try {
        const user = await validateStoredToken(token);
        if (user) {
          set({ user, isAuthenticated: true, hasBackendSession: true, sessionToken: token, isLoading: false });
          return;
        }
        // Token expired — try refresh
        const refreshed = await get()._tryRefresh();
        if (refreshed) return;
      } catch {
        // Token invalid
      }
    }

    // 3. Anonymous
    set({ user: null, isAuthenticated: false, hasBackendSession: false, isLoading: false, sessionToken: null });
  },

  // ── Login via provider (Azure SWA redirect) ──
  loginWithProvider: (provider) => {
    const redirectUri = buildPostLoginRedirectUri();
    const urls = {
      microsoft: `/.auth/login/aad?post_login_redirect_uri=${redirectUri}`,
      google: `/.auth/login/google?post_login_redirect_uri=${redirectUri}`,
      github: `/.auth/login/github?post_login_redirect_uri=${redirectUri}`,
    };
    const url = urls[provider];
    if (url) {
      window.location.href = url;
    }
  },

  // ── Login with token (direct API, for non-SWA deployments) ──
  loginWithToken: async (provider, payload) => {
    try {
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider, ...payload }),
      });
      if (!res.ok) return false;
      const data = await res.json();
      storeTokens(data.session_token, data.refresh_token);
      set({
        user: data.user,
        isAuthenticated: true,
        hasBackendSession: true,
        sessionToken: data.session_token,
      });
      return true;
    } catch {
      return false;
    }
  },

  // ── Logout ──
  logout: async () => {
    const token = get().sessionToken;
    // Invalidate server-side
    try {
      await fetch(`${API_BASE}/auth/logout`, {
        method: 'POST',
        headers: token ? { 'Authorization': `Bearer ${token}` } : {},
      });
    } catch { /* best-effort */ }

    clearTokens();
    set({ user: null, isAuthenticated: false, hasBackendSession: false, sessionToken: null });

    // Also try SWA logout
    try {
      window.location.href = '/.auth/logout?post_logout_redirect_uri=/';
    } catch {
      // Not on SWA
    }
  },

  // ── Internal: try refresh token ──
  _tryRefresh: async () => {
    const refreshToken = getStoredRefresh();
    if (!refreshToken) return false;
    try {
      const res = await fetch(`${API_BASE}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!res.ok) {
        clearTokens();
        return false;
      }
      const data = await res.json();
      storeTokens(data.session_token, data.refresh_token);
      // Re-fetch user with new token
      const userRes = await fetch(`${API_BASE}/auth/me`, {
        headers: {
          'Authorization': `Bearer ${data.session_token}`,
          'Content-Type': 'application/json',
        },
      });
      if (userRes.ok) {
        const user = await userRes.json();
        if (user && user.id) {
          set({
            user,
            isAuthenticated: true,
            hasBackendSession: true,
            sessionToken: data.session_token,
            isLoading: false,
          });
          return true;
        }
      }
      return false;
    } catch {
      clearTokens();
      return false;
    }
  },
}));

export default useAuthStore;
