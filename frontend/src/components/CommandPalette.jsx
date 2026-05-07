import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import {
  Upload, Code, FileText, DollarSign,
  Download, Image, FileDown, MessageSquare, Moon, Sun,
  Copy, ExternalLink, Trash2, Search, Command,
} from 'lucide-react';
import useAppStore from '../stores/useAppStore';

/* ── Fuzzy match: simple substring match on lowercased strings ── */
function fuzzyMatch(query, text) {
  if (!query) return true;
  const q = query.toLowerCase();
  const t = text.toLowerCase();
  if (t.includes(q)) return true;
  // Check if all query chars appear in order
  let qi = 0;
  for (let i = 0; i < t.length && qi < q.length; i++) {
    if (t[i] === q[qi]) qi++;
  }
  return qi === q.length;
}

/* ── Command definitions ── */
function buildCommands(setActiveTab, toggleTheme, theme) {
  return [
    // Navigation
    { id: 'nav-workbench', label: 'Go to Workbench', section: 'Navigation', shortcut: '1', icon: Upload, action: () => setActiveTab('translator') },
    { id: 'nav-iac', label: 'Go to IaC', section: 'Navigation', shortcut: '3', icon: Code, action: () => setActiveTab('translator') },
    { id: 'nav-hld', label: 'Go to HLD', section: 'Navigation', shortcut: '4', icon: FileText, action: () => setActiveTab('translator') },
    { id: 'nav-cost', label: 'Go to Cost', section: 'Navigation', shortcut: '5', icon: DollarSign, action: () => setActiveTab('translator') },
    // Actions
    { id: 'act-export-tf', label: 'Export Terraform', section: 'Actions', shortcut: '⇧⌘T', icon: Download, action: () => { /* dispatched via custom event */ document.dispatchEvent(new CustomEvent('archmorph:command', { detail: 'export-terraform' })); } },
    { id: 'act-export-diag', label: 'Export Diagram', section: 'Actions', shortcut: '⇧⌘D', icon: Image, action: () => { document.dispatchEvent(new CustomEvent('archmorph:command', { detail: 'export-diagram' })); } },
    { id: 'act-export-hub', label: 'Generate All Deliverables', section: 'Actions', shortcut: '⌘E', icon: Download, action: () => { document.dispatchEvent(new CustomEvent('archmorph:command', { detail: 'export-hub' })); } },
    { id: 'act-download-pdf', label: 'Download PDF Report', section: 'Actions', shortcut: '⇧⌘P', icon: FileDown, action: () => { document.dispatchEvent(new CustomEvent('archmorph:command', { detail: 'download-pdf' })); } },
    { id: 'act-toggle-chat', label: 'Toggle IaC Chat', section: 'Actions', shortcut: '⌘/', icon: MessageSquare, action: () => { document.dispatchEvent(new CustomEvent('archmorph:command', { detail: 'toggle-chat' })); } },
    { id: 'act-toggle-dark', label: 'Toggle Dark Mode', section: 'Actions', shortcut: '⇧⌘L', icon: theme === 'dark' ? Sun : Moon, action: toggleTheme },
    // Quick
    { id: 'quick-copy-summary', label: 'Copy Analysis Summary', section: 'Quick', icon: Copy, action: () => { document.dispatchEvent(new CustomEvent('archmorph:command', { detail: 'copy-summary' })); } },
    { id: 'quick-api-docs', label: 'Open API Docs', section: 'Quick', icon: ExternalLink, action: () => { window.open('/api/docs', '_blank', 'noopener'); } },
    { id: 'quick-clear', label: 'Clear Analysis', section: 'Quick', icon: Trash2, action: () => { document.dispatchEvent(new CustomEvent('archmorph:command', { detail: 'clear-analysis' })); } },
  ];
}

export default function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [activeIdx, setActiveIdx] = useState(0);
  const inputRef = useRef(null);
  const listRef = useRef(null);

  const setActiveTab = useAppStore(s => s.setActiveTab);

  // Read theme from localStorage to avoid coupling with Nav's useTheme
  const [theme, setThemeState] = useState(() => {
    try { return localStorage.getItem('archmorph-theme') || 'dark'; } catch { return 'dark'; }
  });
  const toggleTheme = useCallback(() => {
    setThemeState(prev => {
      const next = prev === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      try { localStorage.setItem('archmorph-theme', next); } catch { /* noop */ }
      return next;
    });
  }, []);

  const commands = useMemo(() => buildCommands(setActiveTab, toggleTheme, theme), [setActiveTab, toggleTheme, theme]);

  const filtered = useMemo(() => {
    if (!query) return commands;
    return commands.filter(cmd => fuzzyMatch(query, cmd.label) || fuzzyMatch(query, cmd.section));
  }, [commands, query]);

  // Group by section
  const grouped = useMemo(() => {
    const map = new Map();
    for (const cmd of filtered) {
      if (!map.has(cmd.section)) map.set(cmd.section, []);
      map.get(cmd.section).push(cmd);
    }
    return map;
  }, [filtered]);

  // Reset on open/close
  useEffect(() => {
    if (open) {
      setQuery('');
      setActiveIdx(0);
      // Focus after mount
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  // Scroll active item into view
  useEffect(() => {
    const el = listRef.current?.querySelector(`[data-idx="${activeIdx}"]`);
    el?.scrollIntoView({ block: 'nearest' });
  }, [activeIdx]);

  // ── Global keyboard shortcuts ──
  useEffect(() => {
    function handleKeyDown(e) {
      const isMac = navigator.platform.toUpperCase().includes('MAC');
      const mod = isMac ? e.metaKey : e.ctrlKey;

      // Cmd+K → toggle palette
      if (mod && e.key === 'k') {
        e.preventDefault();
        setOpen(prev => !prev);
        return;
      }

      // Cmd+E → export menu
      if (mod && e.key === 'e' && !e.shiftKey) {
        e.preventDefault();
        document.dispatchEvent(new CustomEvent('archmorph:command', { detail: 'export-menu' }));
        return;
      }

      // Cmd+/ → toggle chat
      if (mod && e.key === '/') {
        e.preventDefault();
        document.dispatchEvent(new CustomEvent('archmorph:command', { detail: 'toggle-chat' }));
        return;
      }

      // Cmd+Shift+T → export terraform
      if (mod && e.shiftKey && e.key === 'T') {
        e.preventDefault();
        document.dispatchEvent(new CustomEvent('archmorph:command', { detail: 'export-terraform' }));
        return;
      }

      // Cmd+Shift+D → export diagram
      if (mod && e.shiftKey && e.key === 'D') {
        e.preventDefault();
        document.dispatchEvent(new CustomEvent('archmorph:command', { detail: 'export-diagram' }));
        return;
      }

      // Cmd+Shift+P → download PDF
      if (mod && e.shiftKey && e.key === 'P') {
        e.preventDefault();
        document.dispatchEvent(new CustomEvent('archmorph:command', { detail: 'download-pdf' }));
        return;
      }

      // Cmd+Shift+L → toggle dark mode
      if (mod && e.shiftKey && e.key === 'L') {
        e.preventDefault();
        toggleTheme();
        return;
      }

      // Esc → close modals
      if (e.key === 'Escape') {
        if (open) {
          e.preventDefault();
          setOpen(false);
        }
      }
    }

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open, toggleTheme]);

  // ── Local keyboard nav inside palette ──
  const handleInputKeyDown = (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIdx(i => Math.min(i + 1, filtered.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIdx(i => Math.max(i - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const cmd = filtered[activeIdx];
      if (cmd) {
        cmd.action();
        setOpen(false);
      }
    } else if (e.key === 'Escape') {
      setOpen(false);
    }
  };

  // Reset activeIdx when query changes
  useEffect(() => { setActiveIdx(0); }, [query]);

  if (!open) return null;

  let flatIdx = 0;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-start justify-center pt-[20vh]"
      onClick={() => setOpen(false)}
      role="dialog"
      aria-modal="true"
      aria-label="Command palette"
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" />

      {/* Card */}
      <div
        className="relative w-full max-w-lg rounded-xl bg-surface border border-border shadow-2xl overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        {/* Search input */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-border/50">
          <Search className="w-5 h-5 text-text-muted shrink-0" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={handleInputKeyDown}
            placeholder="Type a command…"
            className="flex-1 bg-transparent text-sm text-text-primary placeholder-text-muted outline-none"
            aria-label="Search commands"
            autoComplete="off"
            spellCheck={false}
          />
          <kbd className="hidden sm:inline-flex items-center px-1.5 py-0.5 rounded bg-secondary text-text-muted text-[10px] font-mono border border-border/50">ESC</kbd>
        </div>

        {/* Results */}
        <div ref={listRef} className="max-h-[50vh] overflow-y-auto py-2" role="listbox">
          {filtered.length === 0 && (
            <div className="px-4 py-8 text-center text-sm text-text-muted">No commands found</div>
          )}
          {[...grouped.entries()].map(([section, cmds]) => (
            <div key={section}>
              <div className="px-4 py-1.5 text-[10px] font-bold text-text-muted uppercase tracking-wider">{section}</div>
              {cmds.map(cmd => {
                const idx = flatIdx++;
                const isActive = idx === activeIdx;
                const Icon = cmd.icon;
                return (
                  <button
                    key={cmd.id}
                    data-idx={idx}
                    type="button"
                    role="option"
                    aria-selected={isActive}
                    onClick={() => { cmd.action(); setOpen(false); }}
                    onMouseEnter={() => setActiveIdx(idx)}
                    className={`w-full flex items-center gap-3 px-4 py-2 text-left transition-colors cursor-pointer ${
                      isActive ? 'bg-cta/10 text-cta' : 'text-text-secondary hover:bg-secondary/50'
                    }`}
                  >
                    <Icon className="w-4 h-4 shrink-0" />
                    <span className="flex-1 text-sm font-medium">{cmd.label}</span>
                    {cmd.shortcut && (
                      <span className="text-[10px] font-mono text-text-muted bg-secondary px-1.5 py-0.5 rounded">{cmd.shortcut}</span>
                    )}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
