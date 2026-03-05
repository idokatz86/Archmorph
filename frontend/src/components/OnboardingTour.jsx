import React, { useState, useEffect } from 'react';
import { X, Upload, Layers, FileCode, Sparkles, BarChart3, ArrowRight } from 'lucide-react';
import { Button, Card } from './ui';

const TOUR_STEPS = [
  {
    icon: Upload,
    title: 'Upload Your Architecture',
    description: 'Start by uploading any cloud architecture diagram — screenshots, Visio files, or draw.io exports from AWS, GCP, or Azure.',
  },
  {
    icon: Layers,
    title: 'AI Analyzes Your Services',
    description: 'GPT-4o Vision identifies every cloud service, networking component, and security boundary in your diagram automatically.',
  },
  {
    icon: FileCode,
    title: 'Generate Infrastructure as Code',
    description: 'Get production-ready Terraform, Bicep, or CloudFormation code for your target Azure architecture — with an AI chat assistant to modify it.',
  },
  {
    icon: Sparkles,
    title: 'Review Your HLD Document',
    description: 'An AI-generated High-Level Design document covers service architecture, security, networking, migration plan, and WAF alignment.',
  },
  {
    icon: BarChart3,
    title: 'Understand Your Costs',
    description: 'Get SKU-level pricing with specific formulas, alternative options, optimization recommendations, and source vs Azure cost comparison.',
  },
];

export default function OnboardingTour() {
  const [visible, setVisible] = useState(false);
  const [step, setStep] = useState(0);

  useEffect(() => {
    const seen = localStorage.getItem('archmorph-tour-seen');
    if (!seen) setVisible(true);
  }, []);

  const dismiss = () => {
    setVisible(false);
    localStorage.setItem('archmorph-tour-seen', 'true');
  };

  if (!visible) return null;

  const current = TOUR_STEPS[step];
  const Icon = current.icon;
  const isLast = step === TOUR_STEPS.length - 1;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-in fade-in">
      <Card className="w-full max-w-md mx-4 p-6 bg-surface border border-border shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            {TOUR_STEPS.map((_, i) => (
              <div
                key={i}
                className={`w-2 h-2 rounded-full transition-colors ${
                  i === step ? 'bg-cta' : i < step ? 'bg-cta/40' : 'bg-secondary'
                }`}
              />
            ))}
          </div>
          <button onClick={dismiss} className="p-1 hover:bg-secondary rounded cursor-pointer" aria-label="Skip tour">
            <X className="w-4 h-4 text-text-muted" />
          </button>
        </div>

        {/* Content */}
        <div className="text-center py-4">
          <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-cta/10 flex items-center justify-center">
            <Icon className="w-8 h-8 text-cta" />
          </div>
          <h2 className="text-lg font-bold text-text-primary mb-2">{current.title}</h2>
          <p className="text-sm text-text-secondary leading-relaxed">{current.description}</p>
        </div>

        {/* Step counter */}
        <p className="text-xs text-text-muted text-center mb-4">
          Step {step + 1} of {TOUR_STEPS.length}
        </p>

        {/* Actions */}
        <div className="flex items-center justify-between">
          {step > 0 ? (
            <Button onClick={() => setStep(s => s - 1)} variant="ghost" size="sm">
              Back
            </Button>
          ) : (
            <Button onClick={dismiss} variant="ghost" size="sm">
              Skip
            </Button>
          )}
          {isLast ? (
            <Button onClick={dismiss} variant="primary" icon={ArrowRight}>
              Get Started
            </Button>
          ) : (
            <Button onClick={() => setStep(s => s + 1)} variant="primary" icon={ArrowRight}>
              Next
            </Button>
          )}
        </div>
      </Card>
    </div>
  );
}
