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

const TOKEN_KEY = 'archmorph_session_token';
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

const useAuthStore = create((set, get) => ({
  // ── State ──
  user: null,
  isAuthenticated: false,
  isLoading: true,
  sessionToken: getStoredToken(),

  // ── Initialize — call on app mount ──
  initialize: async () => {
    set({ isLoading: true });

    // 1. Try Azure SWA built-in auth (production on Static Web Apps)
    try {
      const res = await fetch('/.auth/me');
      if (res.ok) {
        const data = await res.json();
        const principal = data?.clientPrincipal;
        if (principal?.userId) {
          // SWA authenticated — get full user from our API
          const apiRes = await fetch(`${API_BASE}/auth/me`, {
            headers: { 'Content-Type': 'application/json' },
          });
          if (apiRes.ok) {
            const user = await apiRes.json();
            if (user && user.id) {
              set({ user, isAuthenticated: true, isLoading: false });
              return;
            }
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
        const res = await fetch(`${API_BASE}/auth/me`, {
          headers: {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json',
          },
        });
        if (res.ok) {
          const user = await res.json();
          if (user && user.id) {
            set({ user, isAuthenticated: true, sessionToken: token, isLoading: false });
            return;
          }
        }
        // Token expired — try refresh
        const refreshed = await get()._tryRefresh();
        if (refreshed) return;
      } catch {
        // Token invalid
      }
    }

    // 3. Anonymous
    set({ user: null, isAuthenticated: false, isLoading: false, sessionToken: null });
  },

  // ── Login via provider (Azure SWA redirect) ──
  loginWithProvider: (provider) => {
    const urls = {
      microsoft: '/.auth/login/aad?post_login_redirect_uri=' + encodeURIComponent(window.location.pathname),
      google: '/.auth/login/google?post_login_redirect_uri=' + encodeURIComponent(window.location.pathname),
      github: '/.auth/login/github?post_login_redirect_uri=' + encodeURIComponent(window.location.pathname),
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
    set({ user: null, isAuthenticated: false, sessionToken: null });

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
