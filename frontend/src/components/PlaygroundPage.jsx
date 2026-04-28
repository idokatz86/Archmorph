import React, { useState } from 'react';
import { ArrowRight, Cloud, Layers, FileCode, BarChart3, Download, FileText, Globe2, Network, Boxes } from 'lucide-react';
import { Button, Card, Badge } from './ui';
import useAppStore from '../stores/useAppStore';

/**
 * Interactive Demo Playground (#493).
 * Zero-friction try-it-now experience — no sign-up required.
 * Pre-loads sample diagrams showing the full analysis flow.
 * Shows the free sample workflow without billing or subscription gates.
 */

const PLAYGROUND_SAMPLES = [
  {
    id: 'aws-iaas',
    name: 'AWS 3-Tier Web App',
    provider: 'aws',
    description: 'Classic EC2 + RDS + S3 architecture with ALB and CloudFront',
    services: 6,
    icon: Globe2,
  },
  {
    id: 'aws-eks',
    name: 'AWS Microservices (EKS)',
    provider: 'aws',
    description: 'Containerized microservices on EKS with SQS and DynamoDB',
    services: 8,
    icon: Boxes,
  },
  {
    id: 'gcp-gke',
    name: 'GCP Kubernetes Platform',
    provider: 'gcp',
    description: 'GKE cluster with Cloud SQL, Pub/Sub, and Cloud Storage',
    services: 7,
    icon: Network,
  },
];

const DEMO_FEATURES = [
  { icon: Layers, label: 'AI service detection' },
  { icon: Cloud, label: 'Cross-cloud mapping' },
  { icon: FileCode, label: 'IaC code preview' },
  { icon: BarChart3, label: 'Cost estimation' },
  { icon: Download, label: 'Download IaC code' },
  { icon: FileText, label: 'Export HLD document' },
  { icon: FileText, label: 'PDF report' },
];

export default function PlaygroundPage() {
  const setActiveTab = useAppStore(s => s.setActiveTab);
  const setPendingSample = useAppStore(s => s.setPendingSample);
  const [selectedSample, setSelectedSample] = useState(null);
  const [loading, setLoading] = useState(false);

  const handleTrySample = async (sample) => {
    setSelectedSample(sample.id);
    setLoading(true);
    setPendingSample(sample);
    setTimeout(() => {
      setActiveTab('translator');
      setLoading(false);
    }, 500);
  };

  return (
    <div className="max-w-5xl mx-auto px-4 py-12">
      {/* Hero */}
      <div className="text-center mb-12">
        <Badge variant="azure" className="mb-4">No sign-up required</Badge>
        <h1 className="text-3xl sm:text-4xl font-bold text-text-primary mb-3">
          Start a migration review <span className="text-cta">instantly</span>
        </h1>
        <p className="text-lg text-text-secondary max-w-2xl mx-auto">
          Pick a sample architecture below and see how Archmorph translates it to Azure
          with AI-powered service mapping, IaC generation, and cost estimation.
        </p>
      </div>

      {/* Sample Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-12">
        {PLAYGROUND_SAMPLES.map((sample) => (
          <SampleCard
            key={sample.id}
            sample={sample}
            selected={selectedSample === sample.id}
            loading={loading && selectedSample === sample.id}
            onTry={handleTrySample}
          />
        ))}
      </div>

      {/* What's included */}
      <Card className="p-6 mb-8">
        <h2 className="text-sm font-semibold text-text-primary mb-4">What you get in the playground</h2>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {DEMO_FEATURES.map((feat, i) => (
            <div key={i} className="flex items-center gap-2 text-xs text-text-secondary">
              <feat.icon className="w-3.5 h-3.5 text-cta" />
              <span>{feat.label}</span>
            </div>
          ))}
        </div>
      </Card>

      {/* CTA */}
      <div className="text-center">
        <p className="text-sm text-text-muted mb-3">Use the same free workflow with your own architecture diagram.</p>
        <Button variant="primary" size="lg" icon={ArrowRight} onClick={() => setActiveTab('translator')}>
          Start with your own diagram
        </Button>
      </div>
    </div>
  );
}

function SampleCard({ sample, selected, loading, onTry }) {
  const SampleIcon = sample.icon;
  return (
    <Card
      hover
      className={`p-6 transition-all duration-200 ${selected ? 'border-cta ring-2 ring-cta/20' : ''}`}
    >
      <div className="w-10 h-10 rounded-lg bg-cta/10 flex items-center justify-center mb-3">
        <SampleIcon className="w-5 h-5 text-cta" aria-hidden="true" />
      </div>
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
          loading={loading}
          onClick={() => onTry(sample)}
        >
          Try it
        </Button>
      </div>
    </Card>
  );
}
