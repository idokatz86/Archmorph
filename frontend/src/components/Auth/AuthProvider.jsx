/**
 * AuthProvider — React context wrapper for auth state (#246).
 *
 * Initializes auth on mount (SWA check → localStorage token → anonymous).
 * Provides auth state and actions to the entire component tree.
 */

import React, { createContext, useContext, useEffect } from 'react';
import useAuthStore from '../../stores/useAuthStore';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const initialize = useAuthStore((s) => s.initialize);
  const user = useAuthStore((s) => s.user);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const isLoading = useAuthStore((s) => s.isLoading);
  const loginWithProvider = useAuthStore((s) => s.loginWithProvider);
  const loginWithToken = useAuthStore((s) => s.loginWithToken);
  const logout = useAuthStore((s) => s.logout);

  useEffect(() => {
    initialize();
  }, [initialize]);

  const value = {
    user,
    isAuthenticated,
    isLoading,
    loginWithProvider,
    loginWithToken,
    logout,
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}

export default AuthProvider;
