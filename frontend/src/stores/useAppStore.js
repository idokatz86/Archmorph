/**
 * Global application state store (#170).
 *
 * Manages top-level UI state that was previously in App.jsx useState calls:
 * - activeTab (translator | services | roadmap)
 * - adminOpen
 * - updateStatus (fetched from /api/service-updates/status)
 */

import { create } from 'zustand';
import api from '../services/apiClient';

const useAppStore = create((set) => ({
  // ── UI state ──
  activeTab: 'landing',
  adminOpen: false,
  updateStatus: null,

  // ── Actions ──
  setActiveTab: (tab) => set({ activeTab: tab }),
  setAdminOpen: (open) => set({ adminOpen: open }),
  toggleAdmin: () => set((s) => ({ adminOpen: !s.adminOpen })),

  /** Fetch service-updates status (called once on mount). */
  fetchUpdateStatus: async (signal) => {
    try {
      const data = await api.get('/service-updates/status', signal);
      set({ updateStatus: data });
    } catch {
      // Non-critical — swallow errors
    }
  },
}));

export default useAppStore;
