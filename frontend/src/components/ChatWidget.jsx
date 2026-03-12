import React, { useState, useEffect, useRef } from 'react';
import {
  MessageSquare, X, FileText, Loader2, Send, CheckCircle,
} from 'lucide-react';
import { API_BASE } from '../constants';
import api from '../services/apiClient';
import useAppStore from '../stores/useAppStore';

export default function ChatWidget() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState([
    { role: 'assistant', content: 'Hi! I\'m the Archmorph AI assistant powered by GPT-4o. I can answer questions about cloud architecture, help you with migrations, or **report bugs** and **request features**. What can I help you with?' },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [sessionId] = useState(() => `chat-${crypto.randomUUID()}`);
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);
  // Offset chat button when cookie banner is visible (#215)
  const [cookieBannerVisible, setCookieBannerVisible] = useState(false);

  useEffect(() => {
    // Check cookie consent on mount and after storage changes
    const checkConsent = () => {
      const stored = localStorage.getItem('archmorph_cookie_consent');
      setCookieBannerVisible(!stored);
    };
    checkConsent();
    // Listen for storage changes (banner dismissed)
    window.addEventListener('storage', checkConsent);
    // Also re-check periodically (same-window storage writes don't fire 'storage' events)
    const interval = setInterval(checkConsent, 2000);
    return () => { window.removeEventListener('storage', checkConsent); clearInterval(interval); };
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  // Focus trap: Escape closes chat, Tab cycles within panel (#308)
  const handlePanelKeyDown = (e) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      setOpen(false);
      return;
    }
    if (e.key === 'Tab') {
      const panel = e.currentTarget;
      const focusable = panel.querySelectorAll(
        'button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])'
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey) {
        if (document.activeElement === first) {
          e.preventDefault();
          last.focus();
        }
      } else {
        if (document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    }
  };

  const sendMessage = async () => {
    const text = input.trim();
    if (!text || loading) return;
    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: text }]);
    setLoading(true);

    try {
      const data = await api.post('/chat', { message: text, session_id: sessionId });
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: data.reply,
        action: data.action,
        data: data.data,
      }]);
    } catch {
      setMessages(prev => [...prev, { role: 'assistant', content: 'Sorry, I couldn\'t connect to the server. Please try again.' }]);
    }
    setLoading(false);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const renderContent = (text) => {
    return text.split('\n').map((line, i) => (
      <p key={i} className={i > 0 ? 'mt-1.5' : ''}>
        {line.split(/(\*\*.*?\*\*|\[.*?\]\(.*?\))/).map((part, j) => {
          const boldMatch = part.match(/^\*\*(.*?)\*\*$/);
          if (boldMatch) return <strong key={j} className="font-semibold">{boldMatch[1]}</strong>;
          const linkMatch = part.match(/^\[(.*?)\]\((.*?)\)$/);
          if (linkMatch) {
            // Sanitize URL: only allow http/https protocols (#213 — XSS prevention)
            let href = linkMatch[2];
            if (!/^(https?:\/\/)/i.test(href)) {
              href = "about:blank";
            }
            return <a key={j} href={href} target="_blank" rel="noopener noreferrer" className="text-cta underline cursor-pointer">{linkMatch[1]}</a>;
          }
          return part;
        })}
      </p>
    ));
  };

  return (
    <>
      <button
        onClick={() => setOpen(!open)}
        className={`fixed right-6 z-50 w-14 h-14 rounded-full bg-cta hover:bg-cta-hover text-surface shadow-lg shadow-cta/30 flex items-center justify-center transition-all duration-200 cursor-pointer ${cookieBannerVisible ? 'bottom-36' : 'bottom-6'}`}
        aria-label={open ? 'Close chat' : 'Open chat'}
      >
        {open ? <X className="w-6 h-6" /> : <MessageSquare className="w-6 h-6" />}
      </button>

      {open && (
        <div
          className="fixed bottom-24 right-6 z-50 w-96 max-w-[calc(100vw-2rem)] bg-primary border border-border rounded-2xl shadow-2xl shadow-black/40 flex flex-col overflow-hidden animate-slide-up"
          style={{ height: '500px' }}
          role="dialog"
          aria-label="Archmorph AI Assistant chat"
          aria-modal="true"
          onKeyDown={handlePanelKeyDown}
        >
          <div className="px-4 py-3 bg-secondary border-b border-border flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-cta/15 flex items-center justify-center">
              <MessageSquare className="w-4 h-4 text-cta" />
            </div>
            <div className="flex-1">
              <h3 className="text-sm font-semibold text-text-primary">Archmorph AI Assistant</h3>
              <p className="text-[10px] text-text-muted">Powered by GPT-4o • Ask me anything</p>
            </div>
            <button onClick={() => setOpen(false)} className="p-1 hover:bg-border rounded cursor-pointer" aria-label="Close chat">
              <X className="w-4 h-4 text-text-muted" />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3" role="log" aria-live="polite">
            {messages.map((msg, i) => (
              <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[85%] px-3 py-2 rounded-xl text-sm ${
                  msg.role === 'user'
                    ? 'bg-cta/15 text-text-primary rounded-br-sm'
                    : 'bg-secondary text-text-primary rounded-bl-sm'
                }`}>
                  {renderContent(msg.content)}
                  {msg.action === 'issue_created' && msg.data && (
                    <div className="mt-2 p-2 bg-cta/10 rounded-lg border border-cta/20">
                      <div className="flex items-center gap-1.5 text-xs text-cta font-medium">
                        <CheckCircle className="w-3.5 h-3.5" />
                        Issue #{msg.data.issue_number} created
                      </div>
                    </div>
                  )}
                  {msg.action === 'issue_draft' && msg.data && (
                    <div className="mt-2 p-2 bg-warning/10 rounded-lg border border-warning/20">
                      <div className="flex items-center gap-1.5 text-xs text-warning font-medium">
                        <FileText className="w-3.5 h-3.5" />
                        Draft ready — reply "yes" to create
                      </div>
                    </div>
                  )}
                </div>
              </div>
            ))}
            {loading && (
              <div className="flex justify-start">
                <div className="bg-secondary px-3 py-2 rounded-xl rounded-bl-sm">
                  <Loader2 className="w-4 h-4 text-text-muted animate-spin" />
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          <div className="px-3 py-3 border-t border-border">
            <div className="flex items-center gap-2">
              <input
                ref={inputRef}
                type="text"
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Type a message..."
                aria-label="Chat message"
                className="flex-1 px-3 py-2 bg-surface border border-border rounded-lg text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cta/50 transition-colors"
              />
              <button
                onClick={sendMessage}
                disabled={!input.trim() || loading}
                className="p-2 rounded-lg bg-cta hover:bg-cta-hover text-surface disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer transition-colors"
              >
                <Send className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
