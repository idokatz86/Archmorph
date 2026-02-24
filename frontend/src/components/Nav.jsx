import React, { useRef, useState } from 'react';
import { CloudCog, Layers, Server, Rocket, MessageSquare, Shield, CreditCard, Home, LayoutDashboard, Sparkles, Menu, X } from 'lucide-react';
import { Badge } from './ui';
import { APP_VERSION } from '../constants';
import FeedbackWidget from './FeedbackWidget';
import LanguageSelector from './LanguageSelector';

export default function Nav({ activeTab, setActiveTab, updateStatus }) {
  const feedbackRef = useRef(null);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const NAV_ITEMS = [
    { id: 'landing', label: 'Home', icon: Home },
    { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
    { id: 'translator', label: 'Translator', icon: Layers },
    { id: 'templates', label: 'Templates', icon: Sparkles },
    { id: 'services', label: 'Services', icon: Server },
    { id: 'roadmap', label: 'Roadmap', icon: Rocket },
    { id: 'pricing', label: 'Pricing', icon: CreditCard },
    { id: 'legal', label: 'Legal', icon: Shield },
  ];

  return (
    <>
      <header className="sticky top-0 z-50 bg-surface/80 backdrop-blur-xl border-b border-border">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg bg-cta/15 flex items-center justify-center">
                <CloudCog className="w-5 h-5 text-cta" />
              </div>
              <div>
                <h1 className="text-lg font-bold text-text-primary tracking-tight">Archmorph</h1>
                <p className="text-[10px] text-text-muted font-medium uppercase tracking-wider">Cloud Translator</p>
              </div>
            </div>
            {/* Desktop navigation */}
            <nav aria-label="Main navigation" className="hidden md:flex items-center gap-1">
              {NAV_ITEMS.map(tab => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  aria-current={activeTab === tab.id ? 'page' : undefined}
                  className={`flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg transition-colors duration-200 cursor-pointer ${
                    activeTab === tab.id
                      ? 'bg-cta/10 text-cta'
                      : 'text-text-secondary hover:text-text-primary hover:bg-secondary'
                  }`}
                >
                  <tab.icon className="w-4 h-4" />
                  {tab.label}
                </button>
              ))}
            </nav>
            <div className="flex items-center gap-3">
              {updateStatus && (
                <div className="hidden sm:flex items-center gap-2 text-xs text-text-muted">
                  <div className={`w-2 h-2 rounded-full ${updateStatus.scheduler_running ? 'bg-cta animate-pulse' : 'bg-text-muted'}`} role="status" aria-label={updateStatus.scheduler_running ? 'Catalog live' : 'Catalog idle'} />
                  <span>Catalog {updateStatus.scheduler_running ? 'Live' : 'Idle'}</span>
                </div>
              )}
              <button
                onClick={() => feedbackRef.current?.open()}
                className="p-2 rounded-lg hover:bg-secondary transition-colors cursor-pointer"
                title="Give Feedback"
              >
                <MessageSquare className="w-4 h-4 text-text-secondary hover:text-text-primary" />
              </button>
              <Badge variant="azure" className="hidden sm:inline-flex">v{APP_VERSION}</Badge>
              <LanguageSelector />
              {/* Mobile hamburger */}
              <button
                onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
                className="md:hidden p-2 rounded-lg hover:bg-secondary transition-colors cursor-pointer"
                aria-label={mobileMenuOpen ? 'Close menu' : 'Open menu'}
                aria-expanded={mobileMenuOpen}
              >
                {mobileMenuOpen ? <X className="w-5 h-5 text-text-primary" /> : <Menu className="w-5 h-5 text-text-primary" />}
              </button>
            </div>
          </div>
        </div>
        {/* Mobile menu dropdown */}
        {mobileMenuOpen && (
          <nav className="md:hidden border-t border-border bg-surface/95 backdrop-blur-xl" aria-label="Mobile navigation">
            <div className="max-w-7xl mx-auto px-4 py-3 space-y-1">
              {NAV_ITEMS.map(tab => (
                <button
                  key={tab.id}
                  onClick={() => { setActiveTab(tab.id); setMobileMenuOpen(false); }}
                  aria-current={activeTab === tab.id ? 'page' : undefined}
                  className={`flex items-center gap-3 w-full px-4 py-2.5 text-sm font-medium rounded-lg transition-colors cursor-pointer ${
                    activeTab === tab.id
                      ? 'bg-cta/10 text-cta'
                      : 'text-text-secondary hover:text-text-primary hover:bg-secondary'
                  }`}
                >
                  <tab.icon className="w-4 h-4" />
                  {tab.label}
                </button>
              ))}
            </div>
          </nav>
        )}
      </header>
      <FeedbackWidget ref={feedbackRef} position="top" />
    </>
  );
}
