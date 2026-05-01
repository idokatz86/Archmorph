import React, { useRef, useState, useEffect, useCallback } from 'react';
import { CloudCog, Layers, Server, Activity, Rocket, MessageSquare, LayoutDashboard, Menu, X, Moon, Sun, ChevronDown, Search } from 'lucide-react';
import FeedbackWidget from './FeedbackWidget';
import { UserMenu } from './Auth';
import { isFeatureEnabled } from '../featureFlags';

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

const PRIMARY_ITEMS = [
  { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { id: 'translator', label: 'Translator', icon: Layers },
  { id: 'services', label: 'Services', icon: Server },
];

const MORE_ITEMS = [
  { id: 'drift', label: 'Drift', icon: Activity, feature: 'livingArchitectureDrift' },
  { id: 'roadmap', label: 'Roadmap', icon: Rocket },
].filter(item => !item.feature || isFeatureEnabled(item.feature));

const ALL_ITEMS = [...PRIMARY_ITEMS, ...MORE_ITEMS];

function MoreDropdown({ activeTab, setActiveTab }) {
  const [open, setOpen] = useState(false);
  const [focusIdx, setFocusIdx] = useState(-1);
  const containerRef = useRef(null);
  const itemRefs = useRef([]);
  const hasActiveChild = MORE_ITEMS.some(item => item.id === activeTab);

  // Close on click outside
  useEffect(() => {
    if (!open) return;
    function handleClick(e) {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setOpen(false);
        setFocusIdx(-1);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [open]);

  // Close on Escape, arrow key navigation
  const handleKeyDown = useCallback((e) => {
    if (!open) {
      if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        setOpen(true);
        setFocusIdx(0);
      }
      return;
    }

    switch (e.key) {
      case 'Escape':
        e.preventDefault();
        setOpen(false);
        setFocusIdx(-1);
        containerRef.current?.querySelector('[aria-haspopup]')?.focus();
        break;
      case 'ArrowDown':
        e.preventDefault();
        setFocusIdx(i => (i + 1) % MORE_ITEMS.length);
        break;
      case 'ArrowUp':
        e.preventDefault();
        setFocusIdx(i => (i - 1 + MORE_ITEMS.length) % MORE_ITEMS.length);
        break;
      case 'Home':
        e.preventDefault();
        setFocusIdx(0);
        break;
      case 'End':
        e.preventDefault();
        setFocusIdx(MORE_ITEMS.length - 1);
        break;
      case 'Tab':
        setOpen(false);
        setFocusIdx(-1);
        break;
      default:
        break;
    }
  }, [open]);

  // Focus the active item when focusIdx changes
  useEffect(() => {
    if (open && focusIdx >= 0) {
      itemRefs.current[focusIdx]?.focus();
    }
  }, [open, focusIdx]);

  return (
    <div ref={containerRef} className="relative">
      <button
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => { setOpen(v => !v); setFocusIdx(-1); }}
        onKeyDown={handleKeyDown}
        className={`flex items-center gap-1.5 px-3 py-1.5 text-[13px] font-medium rounded-lg transition-all duration-200 cursor-pointer relative ${
          hasActiveChild
            ? 'bg-cta/10 text-cta shadow-[0_0_12px_-3px] shadow-cta/30'
            : 'text-text-secondary hover:text-text-primary hover:bg-secondary'
        }`}
      >
        More
        <ChevronDown className={`w-3.5 h-3.5 transition-transform duration-200 ${open ? 'rotate-180' : ''}`} />
        {hasActiveChild && (
          <span className="absolute -bottom-[7px] left-2 right-2 h-[2px] bg-cta rounded-full" />
        )}
      </button>

      {open && (
        <div
          role="menu"
          aria-label="More navigation"
          onKeyDown={handleKeyDown}
          className="absolute top-full right-0 mt-1.5 w-44 rounded-lg bg-surface border border-border shadow-lg shadow-black/20 py-1 z-50"
        >
          {MORE_ITEMS.map((item, idx) => (
            <button
              key={item.id}
              ref={el => { itemRefs.current[idx] = el; }}
              role="menuitem"
              tabIndex={focusIdx === idx ? 0 : -1}
              aria-current={activeTab === item.id ? 'page' : undefined}
              onClick={() => { setActiveTab(item.id); setOpen(false); setFocusIdx(-1); }}
              className={`flex items-center gap-2.5 w-full px-3 py-2 text-[13px] font-medium transition-colors cursor-pointer ${
                activeTab === item.id
                  ? 'bg-cta/10 text-cta'
                  : 'text-text-secondary hover:text-text-primary hover:bg-secondary'
              }`}
            >
              <item.icon className="w-4 h-4" />
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function Nav({ activeTab, setActiveTab, updateStatus }) {
  const feedbackRef = useRef(null);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const { theme, toggle: toggleTheme } = useTheme();

  const catalogLive = updateStatus?.scheduler_running;
  const catalogLabel = catalogLive ? 'Catalog syncing — live updates active' : 'Catalog idle';

  return (
    <>
      <header className="sticky top-0 z-50 bg-surface/80 backdrop-blur-xl border-b border-border">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-14">
            {/* Logo — clickable to go Home (#1), catalog dot as tooltip (#10), tagline removed (#2) */}
            <button
              onClick={() => setActiveTab('translator')}
              className="flex items-center gap-2.5 cursor-pointer group"
              aria-label="Go to home"
              title={catalogLabel}
            >
              <div className="relative w-8 h-8 rounded-lg bg-cta/15 flex items-center justify-center">
                <CloudCog className="w-5 h-5 text-cta" />
                {updateStatus && (
                  <span
                    className={`absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full ring-2 ring-surface/80 ${
                      catalogLive ? 'bg-cta animate-pulse' : 'bg-text-muted'
                    }`}
                    role="status"
                    aria-label={catalogLabel}
                  />
                )}
              </div>
              <h1 className="text-base font-bold tracking-tight group-hover:opacity-80 transition-opacity">
                <span className="text-text-primary">Arch</span>
                <span className="text-cta">morph</span>
              </h1>
            </button>

            {/* Desktop navigation — primary 4 + More dropdown (#3, #8) */}
            <nav aria-label="Main navigation" className="hidden md:flex items-center gap-0.5">
              {PRIMARY_ITEMS.map(tab => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  aria-current={activeTab === tab.id ? 'page' : undefined}
                  className={`flex items-center gap-1.5 px-3 py-1.5 text-[13px] font-medium rounded-lg transition-all duration-200 cursor-pointer relative ${
                    activeTab === tab.id
                      ? 'bg-cta/10 text-cta shadow-[0_0_12px_-3px] shadow-cta/30'
                      : 'text-text-secondary hover:text-text-primary hover:bg-secondary'
                  }`}
                >
                  <tab.icon className="w-4 h-4" />
                  {tab.label}
                  {activeTab === tab.id && (
                    <span className="absolute -bottom-[7px] left-2 right-2 h-[2px] bg-cta rounded-full" />
                  )}
                </button>
              ))}
              <MoreDropdown activeTab={activeTab} setActiveTab={setActiveTab} />
            </nav>

            {/* Right controls — tightened gap (#9), icon-only theme (#6), search (#7), badges removed (#4) */}
            <div className="flex items-center gap-2">
              <button
                onClick={() => {
                  const event = new KeyboardEvent('keydown', { key: 'k', metaKey: true, bubbles: true });
                  document.dispatchEvent(event);
                }}
                className="p-1.5 rounded-lg hover:bg-secondary transition-colors cursor-pointer"
                aria-label="Open command palette"
                title="Search (⌘K)"
              >
                <Search className="w-4 h-4 text-text-secondary" />
              </button>
              <button
                onClick={toggleTheme}
                className="p-1.5 rounded-lg hover:bg-secondary transition-colors cursor-pointer"
                aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
                title={theme === 'dark' ? 'Light mode' : 'Dark mode'}
              >
                {theme === 'dark'
                  ? <Moon className="w-4 h-4 text-text-secondary" />
                  : <Sun className="w-4 h-4 text-warning" />
                }
              </button>
              <button
                onClick={() => feedbackRef.current?.open()}
                className="p-1.5 rounded-lg hover:bg-secondary transition-colors cursor-pointer"
                aria-label="Give feedback"
                title="Give feedback"
              >
                <MessageSquare className="w-4 h-4 text-text-secondary" />
              </button>
              <UserMenu />
              {/* Mobile hamburger */}
              <button
                onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
                className="md:hidden p-1.5 rounded-lg hover:bg-secondary transition-colors cursor-pointer"
                aria-label={mobileMenuOpen ? 'Close menu' : 'Open menu'}
                aria-expanded={mobileMenuOpen}
              >
                {mobileMenuOpen ? <X className="w-5 h-5 text-text-primary" /> : <Menu className="w-5 h-5 text-text-primary" />}
              </button>
            </div>
          </div>
        </div>

        {/* Mobile menu — all items visible (#5) */}
        {mobileMenuOpen && (
          <nav className="md:hidden border-t border-border bg-surface/95 backdrop-blur-xl" aria-label="Mobile navigation">
            <div className="max-w-7xl mx-auto px-4 py-3 space-y-1">
              {ALL_ITEMS.map(tab => (
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
