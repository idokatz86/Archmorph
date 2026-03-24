import React, { useRef, useState, useEffect } from 'react';
import { CloudCog, Layers, Server, Activity, Rocket, MessageSquare, Shield, Home, LayoutDashboard, Sparkles, Menu, X, Moon, Sun, PenTool } from 'lucide-react';
import { Badge } from './ui';
import { APP_VERSION } from '../constants';
import FeedbackWidget from './FeedbackWidget';
import { UserMenu } from './Auth';

function useTheme() {
  const [theme, setTheme] = useState(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem('archmorph-theme') || 'dark';
    }
    return 'dark';
  });

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('archmorph-theme', theme);
  }, [theme]);

  const toggle = () => setTheme(t => t === 'dark' ? 'light' : 'dark');
  return { theme, toggle };
}

export default function Nav({ activeTab, setActiveTab, updateStatus }) {
  const feedbackRef = useRef(null);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const { theme, toggle: toggleTheme } = useTheme();

  const NAV_ITEMS = [
    { id: 'landing', label: 'Home', icon: Home },
    { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
    { id: 'playground', label: 'Playground', icon: Sparkles },
    { id: 'translator', label: 'Translator', icon: Layers },
    // { id: 'templates', label: 'Templates', icon: Sparkles }, // Hidden for beta
    { id: 'services', label: 'Services', icon: Server },
    { id: 'canvas', label: 'Canvas', icon: PenTool },
    { id: 'drift', label: 'Drift', icon: Activity },
    { id: 'roadmap', label: 'Roadmap', icon: Rocket },
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
                <h1 className="text-lg font-bold tracking-tight"><span className="text-text-primary">Arch</span><span className="text-cta">morph</span></h1>
                <p className="text-[10px] text-text-muted font-medium uppercase tracking-wider">Modernize Any Cloud</p>
              </div>
            </div>
            {/* Desktop navigation */}
            <nav aria-label="Main navigation" className="hidden md:flex items-center gap-1">
              {NAV_ITEMS.map(tab => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  aria-current={activeTab === tab.id ? 'page' : undefined}
                  className={`flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg transition-all duration-200 cursor-pointer relative ${
                    activeTab === tab.id
                      ? 'bg-cta/10 text-cta'
                      : 'text-text-secondary hover:text-text-primary hover:bg-secondary'
                  }`}
                >
                  <tab.icon className="w-4 h-4" />
                  {tab.label}
                  {activeTab === tab.id && (
                    <span className="absolute -bottom-[9px] left-2 right-2 h-[2px] bg-cta rounded-full" />
                  )}
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
                onClick={toggleTheme}
                className="relative w-14 h-7 rounded-full bg-secondary border border-border hover:border-border-light transition-all duration-300 cursor-pointer flex items-center px-1"
                aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
                title={theme === 'dark' ? 'Light mode' : 'Dark mode'}
              >
                <span className={`absolute w-5 h-5 rounded-full bg-cta/20 flex items-center justify-center transition-transform duration-300 ${theme === 'dark' ? 'translate-x-0' : 'translate-x-7'}`}>
                  {theme === 'dark'
                    ? <Moon className="w-3 h-3 text-info" />
                    : <Sun className="w-3 h-3 text-warning" />
                  }
                </span>
                <Sun className="w-3 h-3 text-text-muted/40 ml-auto mr-0.5" />
                <Moon className="w-3 h-3 text-text-muted/40 ml-0.5" />
              </button>
              <button
                onClick={() => feedbackRef.current?.open()}
                className="p-2 rounded-lg hover:bg-secondary transition-colors cursor-pointer"
                aria-label="Give Feedback"
                title="Give Feedback"
              >
                <MessageSquare className="w-4 h-4 text-text-secondary hover:text-text-primary" />
              </button>
              <UserMenu />
              <span className="hidden lg:inline-flex items-center gap-1 text-[10px] text-text-muted font-mono"><kbd className="px-1 py-0.5 rounded bg-secondary border border-border/50">⌘K</kbd></span>
              <Badge variant="azure" className="hidden sm:inline-flex">v{APP_VERSION}</Badge>
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
