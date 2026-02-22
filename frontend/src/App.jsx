import React, { useState, useEffect, useRef } from 'react';
import 'prismjs/themes/prism-tomorrow.css';
import { AlertTriangle, Code, Coffee } from 'lucide-react';
import ErrorBoundary from './components/ErrorBoundary';
import Nav from './components/Nav';
import DiagramTranslator from './components/DiagramTranslator';
import ServicesBrowser from './components/ServicesBrowser';
import Roadmap from './components/Roadmap';
import ChatWidget from './components/ChatWidget';
import AdminDashboard from './components/AdminDashboard';
import { API_BASE, APP_VERSION } from './constants';

export default function App() {
  const [activeTab, setActiveTab] = useState('translator');
  const [updateStatus, setUpdateStatus] = useState(null);
  const [adminOpen, setAdminOpen] = useState(false);
  const [tapCount, setTapCount] = useState(0);
  const tapTimer = useRef(null);

  useEffect(() => {
    fetch(`${API_BASE}/service-updates/status`)
      .then(r => r.json())
      .then(setUpdateStatus)
      .catch(() => {});
  }, []);

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
          {activeTab === 'translator' && <DiagramTranslator />}
          {activeTab === 'services' && <ServicesBrowser />}
          {activeTab === 'roadmap' && <Roadmap />}
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
            </div>
          </div>
        </div>
      </footer>
      <ChatWidget />
      {adminOpen && <AdminDashboard onClose={() => setAdminOpen(false)} />}
    </div>
  );
}
