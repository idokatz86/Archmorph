import React, { useState } from 'react';
import { X, ThumbsUp, ThumbsDown, Send, MessageSquare, Bug } from 'lucide-react';
import { Button, Card } from './ui';
import { API_BASE } from '../constants';

export default function FeedbackWidget() {
  const [isOpen, setIsOpen] = useState(false);
  const [mode, setMode] = useState('nps'); // 'nps', 'feature', 'bug'
  const [npsScore, setNpsScore] = useState(null);
  const [followUp, setFollowUp] = useState('');
  const [featureContext, setFeatureContext] = useState('');
  const [bugDescription, setBugDescription] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [loading, setLoading] = useState(false);

  const handleSubmitNPS = async () => {
    if (npsScore === null) return;
    setLoading(true);
    try {
      await fetch(`${API_BASE}/feedback/nps`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          score: npsScore,
          follow_up: followUp || null,
          feature_context: featureContext || null,
        }),
      });
      setSubmitted(true);
    } catch {
      // Silently fail
    }
    setLoading(false);
  };

  const handleSubmitFeature = async (helpful) => {
    setLoading(true);
    try {
      await fetch(`${API_BASE}/feedback/feature`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          feature: featureContext || 'general',
          helpful,
          comment: followUp || null,
        }),
      });
      setSubmitted(true);
    } catch {
      // Silently fail
    }
    setLoading(false);
  };

  const handleSubmitBug = async () => {
    if (!bugDescription.trim()) return;
    setLoading(true);
    try {
      await fetch(`${API_BASE}/feedback/bug`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          description: bugDescription,
          severity: 'medium',
          context: {
            url: window.location.href,
            userAgent: navigator.userAgent,
          },
        }),
      });
      setSubmitted(true);
    } catch {
      // Silently fail
    }
    setLoading(false);
  };

  const reset = () => {
    setNpsScore(null);
    setFollowUp('');
    setFeatureContext('');
    setBugDescription('');
    setSubmitted(false);
    setMode('nps');
  };

  if (!isOpen) {
    return (
      <button
        onClick={() => setIsOpen(true)}
        className="fixed bottom-20 right-4 z-40 p-3 rounded-full bg-secondary border border-border shadow-lg hover:bg-cta/20 transition-colors cursor-pointer"
        title="Give Feedback"
      >
        <MessageSquare className="w-5 h-5 text-text-primary" />
      </button>
    );
  }

  return (
    <div className="fixed bottom-20 right-4 z-50 w-80">
      <Card className="p-4 shadow-xl border-cta/30">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-text-primary">Feedback</h3>
          <button onClick={() => { setIsOpen(false); reset(); }} className="cursor-pointer">
            <X className="w-4 h-4 text-text-muted" />
          </button>
        </div>

        {submitted ? (
          <div className="text-center py-6">
            <div className="w-12 h-12 rounded-full bg-cta/20 flex items-center justify-center mx-auto mb-3">
              <ThumbsUp className="w-6 h-6 text-cta" />
            </div>
            <p className="text-sm text-text-primary font-medium">Thank you!</p>
            <p className="text-xs text-text-muted mt-1">Your feedback helps us improve.</p>
            <Button onClick={() => { setIsOpen(false); reset(); }} variant="ghost" size="sm" className="mt-4">
              Close
            </Button>
          </div>
        ) : (
          <>
            {/* Mode Tabs */}
            <div className="flex gap-1 mb-4 bg-secondary rounded-lg p-1">
              {[
                { id: 'nps', label: 'Rate', icon: '⭐' },
                { id: 'feature', label: 'Feature', icon: '💡' },
                { id: 'bug', label: 'Bug', icon: '🐛' },
              ].map(tab => (
                <button
                  key={tab.id}
                  onClick={() => setMode(tab.id)}
                  className={`flex-1 py-1.5 px-2 rounded text-xs font-medium transition-colors cursor-pointer ${
                    mode === tab.id ? 'bg-cta text-white' : 'text-text-muted hover:text-text-primary'
                  }`}
                >
                  {tab.icon} {tab.label}
                </button>
              ))}
            </div>

            {mode === 'nps' && (
              <div className="space-y-4">
                <p className="text-sm text-text-secondary">How likely are you to recommend Archmorph?</p>
                <div className="flex gap-1">
                  {[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map(n => (
                    <button
                      key={n}
                      onClick={() => setNpsScore(n)}
                      className={`w-6 h-8 text-xs rounded cursor-pointer transition-colors ${
                        npsScore === n
                          ? 'bg-cta text-white'
                          : n >= 9
                          ? 'bg-green-500/20 text-green-400 hover:bg-green-500/30'
                          : n >= 7
                          ? 'bg-yellow-500/20 text-yellow-400 hover:bg-yellow-500/30'
                          : 'bg-red-500/20 text-red-400 hover:bg-red-500/30'
                      }`}
                    >
                      {n}
                    </button>
                  ))}
                </div>
                <div className="flex justify-between text-[10px] text-text-muted">
                  <span>Not likely</span>
                  <span>Very likely</span>
                </div>
                <textarea
                  value={followUp}
                  onChange={e => setFollowUp(e.target.value)}
                  placeholder="What could we do better? (optional)"
                  className="w-full p-2 rounded bg-secondary border border-border text-sm text-text-primary placeholder:text-text-muted resize-none"
                  rows={2}
                />
                <Button onClick={handleSubmitNPS} loading={loading} disabled={npsScore === null} icon={Send} className="w-full">
                  Submit
                </Button>
              </div>
            )}

            {mode === 'feature' && (
              <div className="space-y-4">
                <p className="text-sm text-text-secondary">Was this feature helpful?</p>
                <select
                  value={featureContext}
                  onChange={e => setFeatureContext(e.target.value)}
                  className="w-full p-2 rounded bg-secondary border border-border text-sm text-text-primary"
                >
                  <option value="">Select feature...</option>
                  <option value="diagram_analysis">Diagram Analysis</option>
                  <option value="iac_generation">IaC Generation</option>
                  <option value="iac_chat">IaC Chat Assistant</option>
                  <option value="hld_generation">HLD Document</option>
                  <option value="cost_estimate">Cost Estimate</option>
                  <option value="diagram_export">Diagram Export</option>
                  <option value="best_practices">Best Practices</option>
                </select>
                <div className="flex gap-3">
                  <Button onClick={() => handleSubmitFeature(true)} loading={loading} variant="ghost" className="flex-1" icon={ThumbsUp}>
                    Helpful
                  </Button>
                  <Button onClick={() => handleSubmitFeature(false)} loading={loading} variant="ghost" className="flex-1" icon={ThumbsDown}>
                    Not helpful
                  </Button>
                </div>
                <textarea
                  value={followUp}
                  onChange={e => setFollowUp(e.target.value)}
                  placeholder="Any comments? (optional)"
                  className="w-full p-2 rounded bg-secondary border border-border text-sm text-text-primary placeholder:text-text-muted resize-none"
                  rows={2}
                />
              </div>
            )}

            {mode === 'bug' && (
              <div className="space-y-4">
                <p className="text-sm text-text-secondary">Report a bug or issue</p>
                <textarea
                  value={bugDescription}
                  onChange={e => setBugDescription(e.target.value)}
                  placeholder="Describe the issue you encountered..."
                  className="w-full p-2 rounded bg-secondary border border-border text-sm text-text-primary placeholder:text-text-muted resize-none"
                  rows={4}
                />
                <Button onClick={handleSubmitBug} loading={loading} disabled={!bugDescription.trim()} icon={Bug} className="w-full">
                  Report Bug
                </Button>
              </div>
            )}
          </>
        )}
      </Card>
    </div>
  );
}
