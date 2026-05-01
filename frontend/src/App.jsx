import React, { useState, useEffect, useRef, lazy, Suspense } from 'react';
import 'prismjs/themes/prism-tomorrow.css';
import { Code, Coffee, Loader2, Shield } from 'lucide-react';
import ErrorBoundary from './components/ErrorBoundary';
import Nav from './components/Nav';
import Footer from './components/Footer';
import DisclaimerBanner from './components/DisclaimerBanner';
import { ToastProvider } from './components/Toast';
import { AuthProvider } from './components/Auth';
import { APP_VERSION } from './constants';
import useAppStore from './stores/useAppStore';
import { trackPageView } from './services/analytics';
import { isFeatureEnabled } from './featureFlags';

// Lazy-loaded tab components — only fetched when the user switches tabs (#173)
const DiagramTranslator = lazy(() => import('./components/DiagramTranslator'));
const ServicesBrowser = lazy(() => import('./components/ServicesBrowser'));
const Roadmap = lazy(() => import('./components/Roadmap'));
const ChatWidget = lazy(() => import('./components/ChatWidget'));
const DriftDashboard = lazy(() => import('./components/DriftDashboard'));
const AdminDashboard = lazy(() => import('./components/AdminDashboard'));
const LegalPages = lazy(() => import('./components/LegalPages'));
const CookieBanner = lazy(() => import('./components/CookieBanner'));
// PricingPage removed — feature temporarily disabled
const LandingPage = lazy(() => import('./components/LandingPage'));
const OnboardingTour = lazy(() => import('./components/OnboardingTour'));
const CommandPalette = lazy(() => import('./components/CommandPalette'));
const DashboardPage = lazy(() => import('./components/DashboardPage'));
const ApiDocs = lazy(() => import('./components/ApiDocs'));
const CollabWorkspace = lazy(() => import('./components/CollabWorkspace'));
const MigrationReplay = lazy(() => import('./components/MigrationReplay'));


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

  useEffect(() => {
    trackPageView(activeTab);
  }, [activeTab]);

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
    <AuthProvider>
    <ToastProvider>
    <div className="min-h-screen bg-surface text-text-primary font-sans">
      {/* First-time onboarding tour (#257) */}
      <Suspense fallback={null}><OnboardingTour /></Suspense>
      {/* Skip to main content link for keyboard/screen-reader users (#220) */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:px-4 focus:py-2 focus:bg-cta focus:text-surface focus:rounded-lg focus:text-sm focus:font-medium"
      >
        Skip to main content
      </a>
      <DisclaimerBanner />
      <Nav activeTab={activeTab} setActiveTab={setActiveTab} updateStatus={updateStatus} />
      <main id="main-content" className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <ErrorBoundary>
          <Suspense fallback={<TabFallback />}>
            {activeTab === 'landing' && (
              <LandingPage
                onGetStarted={() => setActiveTab('translator')}
                onTrySample={() => setActiveTab('translator')}
              />
            )}
            {activeTab === 'dashboard' && <DashboardPage />}
            {activeTab === 'translator' && <DiagramTranslator />}
            {activeTab === 'services' && <ServicesBrowser />}
            {activeTab === 'roadmap' && <Roadmap />}
            {activeTab === 'drift' && isFeatureEnabled('livingArchitectureDrift') && <DriftDashboard />}
            {activeTab === 'api-docs' && <ApiDocs />}
            {activeTab === 'collab' && <CollabWorkspace />}
            {activeTab === 'replay' && <MigrationReplay />}
            {activeTab === 'legal' && <LegalPages onBack={() => setActiveTab('translator')} />}

          </Suspense>
        </ErrorBoundary>
      </main>
      <Footer handleVersionClick={handleVersionClick} setActiveTab={setActiveTab} />
      <Suspense fallback={null}>
        <ErrorBoundary>
          <ChatWidget />
        </ErrorBoundary>
      </Suspense>
      <Suspense fallback={null}>
        <ErrorBoundary>
          <CookieBanner />
        </ErrorBoundary>
      </Suspense>
      <Suspense fallback={null}>
        <CommandPalette />
      </Suspense>
      {adminOpen && (
        <Suspense fallback={<TabFallback />}>
          <ErrorBoundary>
            <AdminDashboard onClose={() => setAdminOpen(false)} />
          </ErrorBoundary>
        </Suspense>
      )}
    </div>
    </ToastProvider>
    </AuthProvider>
  );
}
