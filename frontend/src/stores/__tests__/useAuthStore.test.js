import { describe, it, expect, vi, beforeEach } from 'vitest';
import useAuthStore, { buildPostLoginRedirectUri } from '../useAuthStore';

const principal = {
  identityProvider: 'aad',
  userId: 'user-123',
  userDetails: 'ido@example.com',
  userRoles: ['anonymous', 'authenticated'],
  claims: [
    { typ: 'name', val: 'Ido Katz' },
    { typ: 'http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress', val: 'ido@example.com' },
  ],
};

function resetAuthStore() {
  useAuthStore.setState({
    user: null,
    isAuthenticated: false,
    hasBackendSession: false,
    isLoading: true,
    sessionToken: null,
  });
}

describe('useAuthStore', () => {
  beforeEach(() => {
    fetch.mockReset();
    localStorage.clear();
    resetAuthStore();
  });

  it('keeps the user signed in after SWA consent even when backend profile is anonymous', async () => {
    fetch
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ clientPrincipal: principal }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ authenticated: false, tier: 'free' }),
      });

    await useAuthStore.getState().initialize();

    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(true);
    expect(state.hasBackendSession).toBe(false);
    expect(state.user).toMatchObject({
      id: 'aad_user-123',
      name: 'Ido Katz',
      email: 'ido@example.com',
      provider: 'microsoft',
    });
  });

  it('prefers the backend user profile when SWA headers reach the API', async () => {
    fetch
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ clientPrincipal: principal }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ id: 'backend-user', name: 'Backend User', provider: 'microsoft' }),
      });

    await useAuthStore.getState().initialize();

    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(true);
    expect(state.hasBackendSession).toBe(true);
    expect(state.user).toMatchObject({ id: 'backend-user', name: 'Backend User' });
  });

  it('falls back to SWA principal profile when /api/auth/me responds with HTML', async () => {
    fetch
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ clientPrincipal: principal }),
      })
      .mockResolvedValueOnce({
        ok: true,
        headers: { get: () => 'text/html' },
        text: () => Promise.resolve('<!DOCTYPE html><html></html>'),
      });

    await useAuthStore.getState().initialize();

    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(true);
    expect(state.hasBackendSession).toBe(false);
    expect(state.user).toMatchObject({
      id: 'aad_user-123',
      name: 'Ido Katz',
      email: 'ido@example.com',
      provider: 'microsoft',
    });
  });

  it('uses a stored backend session before falling back to SWA-only auth', async () => {
    localStorage.setItem('archmorph_session_token', 'valid-backend-token');
    fetch
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ clientPrincipal: principal }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ authenticated: false, tier: 'free' }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ id: 'token-user', name: 'Token User', provider: 'microsoft' }),
      });

    await useAuthStore.getState().initialize();

    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(true);
    expect(state.hasBackendSession).toBe(true);
    expect(state.sessionToken).toBe('valid-backend-token');
    expect(state.user).toMatchObject({ id: 'token-user', name: 'Token User' });
  });

  it('clears a rejected stored backend token before falling back to SWA-only auth', async () => {
    localStorage.setItem('archmorph_session_token', 'stale-backend-token');
    fetch
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ clientPrincipal: principal }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ authenticated: false, tier: 'free' }),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ authenticated: false, tier: 'free' }),
      });

    await useAuthStore.getState().initialize();

    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(true);
    expect(state.hasBackendSession).toBe(false);
    expect(state.sessionToken).toBeNull();
    expect(localStorage.getItem('archmorph_session_token')).toBeNull();
    expect(state.user).toMatchObject({ id: 'aad_user-123' });
  });

  it('preserves a stored backend token when backend validation is indeterminate', async () => {
    localStorage.setItem('archmorph_session_token', 'recoverable-backend-token');
    fetch
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ clientPrincipal: principal }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ authenticated: false, tier: 'free' }),
      })
      .mockRejectedValueOnce(new TypeError('Failed to fetch'));

    await useAuthStore.getState().initialize();

    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(true);
    expect(state.hasBackendSession).toBe(false);
    expect(state.sessionToken).toBeNull();
    expect(localStorage.getItem('archmorph_session_token')).toBe('recoverable-backend-token');
    expect(state.user).toMatchObject({ id: 'aad_user-123' });
  });

  it('preserves path, query string, and hash in SWA login redirects', () => {
    expect(buildPostLoginRedirectUri({
      pathname: '/workspace',
      search: '?project=alpha&view=recent',
      hash: '#dashboard',
    })).toBe('%2Fworkspace%3Fproject%3Dalpha%26view%3Drecent%23dashboard');
  });
});
