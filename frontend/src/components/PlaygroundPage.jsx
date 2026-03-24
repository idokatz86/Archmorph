import React, { useState } from 'react';
import { Upload, ArrowRight, Cloud, Layers, FileCode, BarChart3, Lock } from 'lucide-react';
import { Button, Card, Badge } from './ui';
import useAppStore from '../stores/useAppStore';

/**
 * Interactive Demo Playground (#493).
 * Zero-friction try-it-now experience — no sign-up required.
 * Pre-loads sample diagrams showing the full analysis flow.
 * Gates advanced features (download, export) behind sign-up CTA.
 */

const PLAYGROUND_SAMPLES = [
  {
    id: 'aws-iaas',
    name: 'AWS 3-Tier Web App',
    provider: 'aws',
    description: 'Classic EC2 + RDS + S3 architecture with ALB and CloudFront',
    services: 6,
    icon: '🌐',
  },
  {
    id: 'aws-eks',
    name: 'AWS Microservices (EKS)',
    provider: 'aws',
    description: 'Containerized microservices on EKS with SQS and DynamoDB',
    services: 8,
    icon: '🐳',
  },
  {
    id: 'gcp-gke',
    name: 'GCP Kubernetes Platform',
    provider: 'gcp',
    description: 'GKE cluster with Cloud SQL, Pub/Sub, and Cloud Storage',
    services: 7,
    icon: '⚡',
  },
];

const DEMO_FEATURES = [
  { icon: Layers, label: 'AI service detection', available: true },
  { icon: Cloud, label: 'Cross-cloud mapping', available: true },
  { icon: FileCode, label: 'IaC code preview', available: true },
  { icon: BarChart3, label: 'Cost estimation', available: true },
  { icon: Lock, label: 'Download IaC code', available: false, gated: true },
  { icon: Lock, label: 'Export HLD document', available: false, gated: true },
  { icon: Lock, label: 'PDF report', available: false, gated: true },
];

export default function PlaygroundPage() {
  const setActiveTab = useAppStore(s => s.setActiveTab);
  const [selectedSample, setSelectedSample] = useState(null);
  const [loading, setLoading] = useState(false);

  const handleTrySample = async (sample) => {
    setSelectedSample(sample.id);
    setLoading(true);
    // Navigate to translator with sample pre-loaded
    // The translator already supports onLoadSample
    setTimeout(() => {
      setActiveTab('translator');
      // Dispatch sample load event
      window.dispatchEvent(new CustomEvent('archmorph-load-sample', { detail: { sampleId: sample.id } }));
      setLoading(false);
    }, 500);
  };

  return (
    <div className="max-w-5xl mx-auto px-4 py-12">
      {/* Hero */}
      <div className="text-center mb-12">
        <Badge variant="azure" className="mb-4">No sign-up required</Badge>
        <h1 className="text-3xl sm:text-4xl font-bold text-text-primary mb-3">
          Try Archmorph <span className="text-cta">instantly</span>
        </h1>
        <p className="text-lg text-text-secondary max-w-2xl mx-auto">
          Pick a sample architecture below and see how Archmorph translates it to Azure
          with AI-powered service mapping, IaC generation, and cost estimation.
        </p>
      </div>

      {/* Sample Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-12">
        {PLAYGROUND_SAMPLES.map((sample) => (
          <Card
            key={sample.id}
            hover
            className={`p-6 transition-all duration-200 ${
              selectedSample === sample.id ? 'border-cta ring-2 ring-cta/20' : ''
            }`}
          >
            <div className="text-3xl mb-3">{sample.icon}</div>
            <div className="flex items-center gap-2 mb-2">
              <h3 className="text-sm font-semibold text-text-primary">{sample.name}</h3>
              <Badge variant={sample.provider}>{sample.provider.toUpperCase()}</Badge>
            </div>
            <p className="text-xs text-text-muted mb-3">{sample.description}</p>
            <div className="flex items-center justify-between">
              <span className="text-xs text-text-muted">{sample.services} services</span>
              <Button
                size="sm"
                variant="primary"
                icon={ArrowRight}
                loading={loading && selectedSample === sample.id}
                onClick={() => handleTrySample(sample)}
              >
                Try it
              </Button>
            </div>
          </Card>
        ))}
      </div>

      {/* What's included */}
      <Card className="p-6 mb-8">
        <h2 className="text-sm font-semibold text-text-primary mb-4">What you get in the playground</h2>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {DEMO_FEATURES.map((feat, i) => (
            <div key={i} className={`flex items-center gap-2 text-xs ${feat.gated ? 'text-text-muted' : 'text-text-secondary'}`}>
              <feat.icon className={`w-3.5 h-3.5 ${feat.gated ? 'text-text-muted' : 'text-cta'}`} />
              <span>{feat.label}</span>
              {feat.gated && <Badge variant="default">Pro</Badge>}
            </div>
          ))}
        </div>
      </Card>

      {/* CTA */}
      <div className="text-center">
        <p className="text-sm text-text-muted mb-3">Want full access? Downloads, exports, history, and more.</p>
        <Button variant="primary" size="lg" icon={ArrowRight} onClick={() => setActiveTab('translator')}>
          Sign up free
        </Button>
      </div>
    </div>
  );
}
