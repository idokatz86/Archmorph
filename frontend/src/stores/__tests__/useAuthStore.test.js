import { describe, it, expect, vi, beforeEach } from 'vitest';
import useAuthStore from '../useAuthStore';

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
    expect(state.user).toMatchObject({ id: 'backend-user', name: 'Backend User' });
  });
});