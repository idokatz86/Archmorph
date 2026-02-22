import React, { useState, useEffect, useRef, lazy, Suspense } from 'react';
import 'prismjs/themes/prism-tomorrow.css';
import { AlertTriangle, Code, Coffee, Loader2, Shield } from 'lucide-react';
import ErrorBoundary from './components/ErrorBoundary';
import Nav from './components/Nav';
import DiagramTranslator from './components/DiagramTranslator';
import { APP_VERSION } from './constants';
import useAppStore from './stores/useAppStore';

// Lazy-loaded tab components — only fetched when the user switches tabs (#173)
const ServicesBrowser = lazy(() => import('./components/ServicesBrowser'));
const Roadmap = lazy(() => import('./components/Roadmap'));
const ChatWidget = lazy(() => import('./components/ChatWidget'));
const AdminDashboard = lazy(() => import('./components/AdminDashboard'));
const LegalPages = lazy(() => import('./components/LegalPages'));
const CookieBanner = lazy(() => import('./components/CookieBanner'));
const PricingPage = lazy(() => import('./components/PricingPage'));
const LandingPage = lazy(() => import('./components/LandingPage'));

function TabFallback() {
  return (
    <div className="flex items-center justify-center py-24">
      <Loader2 className="w-6 h-6 text-cta animate-spin" />
      <span className="ml-2 text-sm text-text-muted">Loading…</span>
    </div>
  );
}

export default function App() {
  // Global state from Zustand store (#170)
  const activeTab = useAppStore((s) => s.activeTab);
  const setActiveTab = useAppStore((s) => s.setActiveTab);
  const updateStatus = useAppStore((s) => s.updateStatus);
  const adminOpen = useAppStore((s) => s.adminOpen);
  const setAdminOpen = useAppStore((s) => s.setAdminOpen);
  const fetchUpdateStatus = useAppStore((s) => s.fetchUpdateStatus);

  // Local-only state (easter egg, no need to share)
  const [tapCount, setTapCount] = useState(0);
  const tapTimer = useRef(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchUpdateStatus(controller.signal);
    return () => controller.abort();
  }, [fetchUpdateStatus]);

  useEffect(() => () => clearTimeout(tapTimer.current), []);

  const handleVersionClick = () => {
    const next = tapCount + 1;
    setTapCount(next);
    clearTimeout(tapTimer.current);
    if (next >= 5) {
      setAdminOpen(true);
      setTapCount(0);
    } else {
      tapTimer.current = setTimeout(() => setTapCount(0), 2000);
    }
  };

  return (
    <div className="min-h-screen bg-surface text-text-primary font-sans">
      <Nav activeTab={activeTab} setActiveTab={setActiveTab} updateStatus={updateStatus} />
      <div className="bg-amber-500/10 border-b border-amber-500/20">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-2 flex items-center justify-center gap-2">
          <AlertTriangle className="w-3.5 h-3.5 text-amber-400 shrink-0" />
          <p className="text-xs text-amber-300">
            <span className="font-semibold">Beta Preview</span> — This application is currently in beta. Features and outputs may change. Please review all results before using in production environments.
          </p>
        </div>
      </div>
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <ErrorBoundary>
          <Suspense fallback={<TabFallback />}>
            {activeTab === 'landing' && <LandingPage onGetStarted={() => setActiveTab('translator')} onViewPricing={() => setActiveTab('pricing')} />}
            {activeTab === 'translator' && <DiagramTranslator />}
            {activeTab === 'services' && <ServicesBrowser />}
            {activeTab === 'roadmap' && <Roadmap />}
            {activeTab === 'legal' && <LegalPages onBack={() => setActiveTab('translator')} />}
            {activeTab === 'pricing' && <PricingPage onBack={() => setActiveTab('translator')} />}
          </Suspense>
        </ErrorBoundary>
      </main>
      <footer className="border-t border-border py-8 mt-12">
        <div className="max-w-7xl mx-auto px-4">
          <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
            <p
              className="text-xs text-text-muted select-none cursor-default"
              onClick={handleVersionClick}
            >
              Archmorph v{APP_VERSION} — AI-powered Cloud Architecture Translator to Azure
            </p>
            <div className="flex items-center gap-4">
              <a href="https://github.com/idokatz86/Archmorph" target="_blank" rel="noopener noreferrer" className="flex items-center gap-1.5 text-xs text-text-secondary hover:text-cta transition-colors cursor-pointer">
                <Code className="w-3.5 h-3.5" />
                GitHub
              </a>
              <a href="https://buymeacoffee.com/idokatz" target="_blank" rel="noopener noreferrer" className="flex items-center gap-1.5 text-xs text-text-secondary hover:text-amber-400 transition-colors cursor-pointer">
                <Coffee className="w-3.5 h-3.5" />
                Buy me a coffee
              </a>
              <button
                onClick={() => setActiveTab('legal')}
                className="flex items-center gap-1.5 text-xs text-text-secondary hover:text-cta transition-colors cursor-pointer"
              >
                <Shield className="w-3.5 h-3.5" />
                Legal & Privacy
              </button>
            </div>
          </div>
        </div>
      </footer>
      <Suspense fallback={null}>
        <ChatWidget />
      </Suspense>
      <Suspense fallback={null}>
        <CookieBanner />
      </Suspense>
      {adminOpen && (
        <Suspense fallback={<TabFallback />}>
          <AdminDashboard onClose={() => setAdminOpen(false)} />
        </Suspense>
      )}
    </div>
  );
}
