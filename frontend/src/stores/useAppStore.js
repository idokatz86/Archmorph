/**
 * Global application state store (#170).
 *
 * Manages top-level UI state that was previously in App.jsx useState calls:
 * - activeTab (see VALID_TABS below for the full set of supported values)
 * - adminOpen
 * - updateStatus (fetched from /api/service-updates/status)
 *
 * URL hash sync (#310): activeTab ↔ window.location.hash
 */

import { create } from 'zustand';
import api from '../services/apiClient';

const VALID_TABS = new Set([
  'dashboard',
  'translator',
  'services',
  'templates',
  'roadmap',
  'drift',
  'api-docs',
  'collab',
  'replay',
]);

/** Read initial tab from URL hash, default to the translator. */
function getInitialTab() {
  if (typeof window === 'undefined') return 'translator';
  const hash = window.location.hash.replace('#', '').replace('/', '');
  if (hash === '') return 'translator';
  return VALID_TABS.has(hash) ? hash : 'translator';
}

const useAppStore = create((set) => {
  // Listen for browser back/forward navigation (#310)
  if (typeof window !== 'undefined') {
    window.addEventListener('popstate', () => {
      const hash = window.location.hash.replace('#', '').replace('/', '');
      if (hash === '') {
        set({ activeTab: 'translator' });
      } else if (VALID_TABS.has(hash)) {
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
    pendingTemplateAnalysis: null,

    // ── Actions ──
    setActiveTab: (tab) => {
      set({ activeTab: tab });
      // Sync URL hash (#310)
      if (typeof window !== 'undefined') {
        const newHash = tab === 'translator' ? '' : `#${tab}`;
        const currentHash = window.location.hash === '#translator' ? '' : window.location.hash;
        if (currentHash !== newHash) {
          window.history.pushState(null, '', newHash || window.location.pathname);
        }
      }
    },
    setPendingResumeId: (id) => set({ pendingResumeId: id }),
    setPendingTemplateAnalysis: (analysis) => set({ pendingTemplateAnalysis: analysis }),
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
