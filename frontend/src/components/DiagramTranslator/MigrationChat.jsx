import React, { useState, useRef, useEffect } from 'react';
import { MessageSquare, Send, X, Loader2, Sparkles, ChevronDown, ChevronUp } from 'lucide-react';
import { Button, Card, Badge } from '../ui';
import api from '../../services/apiClient';
import { toRenderableString } from '../../utils/toRenderableString';

const SUGGESTED_QUESTIONS = [
  'What are the biggest risks in this migration?',
  'Which services need the most rework?',
  'How should I handle data migration?',
  'What networking changes are required?',
  'What Azure SKUs do you recommend?',
  'How long will this migration take?',
];

export default function MigrationChat({ diagramId }) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content: 'Hi! I\'m your **Migration Advisor**. Ask me anything about your architecture migration — risks, timeline, Azure service alternatives, networking, security, or cost optimization.',
    },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const endRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 100);
  }, [open]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const send = async (text) => {
    const msg = (text || input).trim();
    if (!msg || loading) return;
    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: msg }]);
    setLoading(true);
    try {
      const data = await api.post(`/diagrams/${diagramId}/migration-chat`, { message: msg });
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: data.reply || 'Sorry, I couldn\'t process that.',
        services: data.related_services || [],
      }]);
    } catch {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: 'Sorry, I couldn\'t connect to the migration advisor. Please try again.',
      }]);
    }
    setLoading(false);
  };

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="fixed bottom-6 left-6 z-40 flex items-center gap-2 px-4 py-2.5 bg-cta text-surface rounded-full shadow-lg hover:bg-cta-hover transition-all cursor-pointer"
        aria-label="Open Migration Advisor"
      >
        <MessageSquare className="w-4 h-4" />
        <span className="text-sm font-medium">Ask about this migration</span>
      </button>
    );
  }

  return (
    <div className="fixed bottom-6 left-6 z-40 w-96 max-w-[calc(100vw-2rem)] bg-surface border border-border rounded-2xl shadow-2xl flex flex-col" style={{ maxHeight: '70vh' }}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border bg-secondary/30 rounded-t-2xl">
        <div className="flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-cta" />
          <span className="text-sm font-semibold text-text-primary">Migration Advisor</span>
          <Badge variant="high" className="text-[9px]">AI</Badge>
        </div>
        <button onClick={() => setOpen(false)} className="p-1 hover:bg-secondary rounded cursor-pointer" aria-label="Close">
          <X className="w-4 h-4 text-text-muted" />
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3" style={{ minHeight: '200px' }}>
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[85%] rounded-xl px-3 py-2 text-xs leading-relaxed ${
              m.role === 'user'
                ? 'bg-cta/15 text-text-primary'
                : 'bg-secondary text-text-secondary'
            }`}>
              {m.content.split('**').map((part, j) =>
                j % 2 === 1 ? <strong key={j}>{part}</strong> : <span key={j}>{part}</span>
              )}
              {Array.isArray(m.services) && m.services.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-1.5">
                  {m.services.map((s, j) => {
                    const text = toRenderableString(s);
                    if (!text) return null;
                    return (
                      <Badge key={j} variant="azure" className="text-[9px]">{text}</Badge>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-secondary rounded-xl px-3 py-2">
              <Loader2 className="w-4 h-4 text-cta animate-spin" />
            </div>
          </div>
        )}
        <div ref={endRef} />
      </div>

      {/* Suggested questions (show only if few messages) */}
      {messages.length <= 2 && (
        <div className="px-4 pb-2">
          <p className="text-[10px] text-text-muted mb-1.5">Try asking:</p>
          <div className="flex flex-wrap gap-1">
            {SUGGESTED_QUESTIONS.slice(0, 4).map((q, i) => (
              <button
                key={i}
                onClick={() => send(q)}
                className="text-[10px] px-2 py-1 rounded-full bg-secondary text-text-secondary hover:bg-cta/10 hover:text-cta cursor-pointer transition-colors"
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Input */}
      <div className="px-3 py-2 border-t border-border flex gap-2">
        <input
          ref={inputRef}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && !e.shiftKey && send()}
          placeholder="Ask about your migration..."
          className="flex-1 text-xs bg-secondary rounded-lg px-3 py-2 text-text-primary placeholder-text-muted outline-none focus:ring-1 focus:ring-cta"
          disabled={loading}
        />
        <button
          onClick={() => send()}
          disabled={!input.trim() || loading}
          className="p-2 rounded-lg bg-cta text-surface hover:bg-cta-hover disabled:opacity-40 cursor-pointer transition-colors"
          aria-label="Send"
        >
          <Send className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  );
}
