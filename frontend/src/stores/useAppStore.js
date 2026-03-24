/**
 * Global application state store (#170).
 *
 * Manages top-level UI state that was previously in App.jsx useState calls:
 * - activeTab (translator | services | roadmap)
 * - adminOpen
 * - updateStatus (fetched from /api/service-updates/status)
 *
 * URL hash sync (#310): activeTab ↔ window.location.hash
 */

import { create } from 'zustand';
import api from '../services/apiClient';

const VALID_TABS = new Set(['landing', 'dashboard', 'playground', 'translator', 'services', 'roadmap', 'legal']);

/** Read initial tab from URL hash, default to 'landing' */
function getInitialTab() {
  if (typeof window === 'undefined') return 'landing';
  const hash = window.location.hash.replace('#', '').replace('/', '');
  return VALID_TABS.has(hash) ? hash : 'landing';
}

const useAppStore = create((set) => {
  // Listen for browser back/forward navigation (#310)
  if (typeof window !== 'undefined') {
    window.addEventListener('popstate', () => {
      const hash = window.location.hash.replace('#', '').replace('/', '');
      if (VALID_TABS.has(hash)) {
        set({ activeTab: hash });
      }
    });
  }

  return {
    // ── UI state ──
    activeTab: getInitialTab(),
    adminOpen: false,
    updateStatus: null,
    pendingResumeId: null,

    // ── Actions ──
    setActiveTab: (tab) => {
      set({ activeTab: tab });
      // Sync URL hash (#310)
      if (typeof window !== 'undefined') {
        const newHash = tab === 'landing' ? '' : `#${tab}`;
        if (window.location.hash !== `#${tab}`) {
          window.history.pushState(null, '', newHash || window.location.pathname);
        }
      }
    },
    setPendingResumeId: (id) => set({ pendingResumeId: id }),
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
  };
});

export default useAppStore;
