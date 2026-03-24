import React, { useState } from 'react';
import { ExternalLink, Copy, Check, Book, Code, Shield, BarChart3, Cloud, Rocket, Key } from 'lucide-react';
import { Button, Card, Tabs } from './ui';

const API_BASE = '/api';

const CATEGORIES = [
  { icon: Key, label: 'Authentication', description: 'OAuth2 login, token refresh, session management' },
  { icon: BarChart3, label: 'Analysis', description: 'Architecture analysis, modernization recommendations' },
  { icon: Code, label: 'IaC Generation', description: 'Generate Terraform, Bicep, Pulumi from diagrams' },
  { icon: BarChart3, label: 'Cost Estimation', description: 'Cloud cost estimates for target architectures' },
  { icon: Cloud, label: 'Cloud Scanner', description: 'Live cloud resource discovery and inventory' },
  { icon: Rocket, label: 'Deployments', description: 'Deploy generated IaC to cloud providers' },
];

const EXAMPLE_ENDPOINTS = [
  {
    method: 'POST',
    path: '/api/v1/analyze',
    description: 'Analyze an architecture diagram and receive modernization recommendations.',
    curl: `curl -X POST ${window.location.origin}/api/v1/analyze \\
  -H "Authorization: Bearer <token>" \\
  -H "Content-Type: multipart/form-data" \\
  -F "file=@architecture.png"`,
  },
  {
    method: 'POST',
    path: '/api/v1/generate',
    description: 'Generate IaC code from analysis results for a target cloud provider.',
    curl: `curl -X POST ${window.location.origin}/api/v1/generate \\
  -H "Authorization: Bearer <token>" \\
  -H "Content-Type: application/json" \\
  -d '{"analysis_id": "abc-123", "target": "azure", "iac": "terraform"}'`,
  },
  {
    method: 'GET',
    path: '/api/v1/services',
    description: 'List available cloud services with mapping metadata.',
    curl: `curl ${window.location.origin}/api/v1/services \\
  -H "Authorization: Bearer <token>"`,
  },
];

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = () => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <button
      onClick={handleCopy}
      className="p-1.5 rounded-md hover:bg-secondary transition-colors cursor-pointer"
      aria-label="Copy to clipboard"
    >
      {copied ? <Check className="w-3.5 h-3.5 text-cta" /> : <Copy className="w-3.5 h-3.5 text-text-muted" />}
    </button>
  );
}

function MethodBadge({ method }) {
  const colors = {
    GET: 'bg-cta/15 text-cta',
    POST: 'bg-info/15 text-info',
    PUT: 'bg-warning/15 text-warning',
    DELETE: 'bg-danger/15 text-danger',
  };
  return (
    <span className={`px-2 py-0.5 text-xs font-bold rounded ${colors[method] || 'bg-secondary text-text-muted'}`}>
      {method}
    </span>
  );
}

export default function ApiDocs() {
  const tabs = [
    { id: 'overview', label: 'Overview', icon: Book },
    { id: 'examples', label: 'Examples', icon: Code },
  ];
  const [activeTab, setActiveTab] = useState('overview');

  return (
    <div className="animate-fade-in space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-text-primary">API Documentation</h2>
          <p className="text-sm text-text-muted mt-1">
            Explore the Archmorph REST API — auto-generated from our FastAPI backend.
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="primary"
            size="sm"
            icon={ExternalLink}
            onClick={() => window.open(`${API_BASE}/docs`, '_blank', 'noopener')}
          >
            Swagger UI
          </Button>
          <Button
            variant="secondary"
            size="sm"
            icon={Book}
            onClick={() => window.open(`${API_BASE}/redoc`, '_blank', 'noopener')}
          >
            ReDoc
          </Button>
        </div>
      </div>

      <Tabs tabs={tabs} activeTab={activeTab} onChange={setActiveTab} />

      {activeTab === 'overview' && (
        <div className="space-y-4 animate-slide-up">
          <h3 className="text-lg font-semibold text-text-primary">API Categories</h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {CATEGORIES.map((cat) => (
              <Card key={cat.label} className="p-4 hover:border-border-light transition-colors">
                <div className="flex items-start gap-3">
                  <div className="w-9 h-9 rounded-lg bg-cta/10 flex items-center justify-center shrink-0">
                    <cat.icon className="w-4 h-4 text-cta" />
                  </div>
                  <div>
                    <h4 className="text-sm font-semibold text-text-primary">{cat.label}</h4>
                    <p className="text-xs text-text-muted mt-0.5">{cat.description}</p>
                  </div>
                </div>
              </Card>
            ))}
          </div>

          <Card className="p-5">
            <div className="flex items-start gap-3">
              <Shield className="w-5 h-5 text-warning shrink-0 mt-0.5" />
              <div>
                <h4 className="text-sm font-semibold text-text-primary">Authentication</h4>
                <p className="text-xs text-text-muted mt-1 leading-relaxed">
                  All API endpoints require a Bearer token obtained via the <code className="px-1 py-0.5 rounded bg-secondary text-cta text-[11px]">/api/v1/auth/login</code> endpoint.
                  Include <code className="px-1 py-0.5 rounded bg-secondary text-cta text-[11px]">Authorization: Bearer &lt;token&gt;</code> in your request headers.
                </p>
              </div>
            </div>
          </Card>
        </div>
      )}

      {activeTab === 'examples' && (
        <div className="space-y-4 animate-slide-up">
          <h3 className="text-lg font-semibold text-text-primary">Example Requests</h3>
          {EXAMPLE_ENDPOINTS.map((ep, i) => (
            <Card key={i} className="overflow-hidden">
              <div className="flex items-center justify-between px-4 py-3 border-b border-border">
                <div className="flex items-center gap-3">
                  <MethodBadge method={ep.method} />
                  <code className="text-sm text-text-primary font-mono">{ep.path}</code>
                </div>
                <CopyButton text={ep.curl} />
              </div>
              <div className="px-4 py-2">
                <p className="text-xs text-text-muted">{ep.description}</p>
              </div>
              <pre className="px-4 py-3 bg-secondary/50 overflow-x-auto text-xs text-text-secondary font-mono leading-relaxed">
                {ep.curl}
              </pre>
            </Card>
          ))}

          <div className="text-center pt-2">
            <Button
              variant="secondary"
              size="sm"
              icon={ExternalLink}
              onClick={() => window.open(`${API_BASE}/docs`, '_blank', 'noopener')}
            >
              Try it in Swagger UI
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
