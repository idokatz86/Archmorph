/**
 * Infrastructure Import panel (#155).
 *
 * Allows users to upload or paste IaC files (Terraform state, HCL,
 * CloudFormation, ARM templates, Kubernetes manifests, Docker Compose)
 * and parse them into Archmorph analysis format for mapping.
 */

import React, { useState, useCallback, useRef } from 'react';
import { Upload, FileCode2, Loader2, AlertTriangle, CheckCircle2, RefreshCw, ClipboardPaste, X } from 'lucide-react';
import { Card, Badge, Button } from './ui';
import api from '../services/apiClient';

const FORMATS = [
  { id: 'auto', label: 'Auto-detect', description: 'Let Archmorph detect the format' },
  { id: 'terraform_state', label: 'Terraform State', description: '.tfstate JSON files' },
  { id: 'terraform_hcl', label: 'Terraform HCL', description: '.tf configuration files' },
  { id: 'cloudformation', label: 'CloudFormation', description: 'AWS CFN templates (JSON/YAML)' },
  { id: 'arm_template', label: 'ARM Template', description: 'Azure Resource Manager JSON' },
  { id: 'kubernetes', label: 'Kubernetes', description: 'K8s manifests (YAML)' },
  { id: 'docker_compose', label: 'Docker Compose', description: 'docker-compose.yml files' },
];

export default function InfraImportPanel({ onImportComplete }) {
  const [content, setContent] = useState('');
  const [format, setFormat] = useState('auto');
  const [fileName, setFileName] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const fileRef = useRef(null);

  const handleFileUpload = useCallback((e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setFileName(file.name);
    const reader = new FileReader();
    reader.onload = (ev) => setContent(ev.target.result);
    reader.onerror = () => setError('Failed to read file');
    reader.readAsText(file);
  }, []);

  const handlePaste = useCallback(async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (text) {
        setContent(text);
        setFileName('clipboard');
      }
    } catch {
      setError('Could not access clipboard');
    }
  }, []);

  const handleImport = useCallback(async () => {
    if (!content.trim()) {
      setError('Please upload a file or paste IaC content');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const body = { content, format: format === 'auto' ? undefined : format };
      const data = await api.post('/import/infrastructure', body);
      setResult(data);
      if (onImportComplete) onImportComplete(data);
    } catch (err) {
      setError(err.message || 'Import failed');
    } finally {
      setLoading(false);
    }
  }, [content, format, onImportComplete]);

  const handleReset = () => {
    setContent('');
    setFileName('');
    setResult(null);
    setError(null);
    if (fileRef.current) fileRef.current.value = '';
  };

  // ── Success state ──
  if (result) {
    const analysis = result.analysis || result;
    const mappingCount = analysis.mappings?.length || 0;
    const zoneCount = analysis.zones?.length || 0;

    return (
      <div className="space-y-4">
        <Card className="p-6">
          <div className="flex items-center gap-3 mb-4">
            <div className="w-10 h-10 rounded-lg bg-green-500/15 flex items-center justify-center">
              <CheckCircle2 className="w-5 h-5 text-green-400" />
            </div>
            <div>
              <h3 className="text-lg font-semibold text-text-primary">Import Successful</h3>
              <p className="text-sm text-text-muted">
                Detected <Badge variant="azure">{result.detected_format || format}</Badge> — {mappingCount} services, {zoneCount} zones
              </p>
            </div>
          </div>

          {/* Service summary */}
          {analysis.mappings && analysis.mappings.length > 0 && (
            <div className="mt-4">
              <h4 className="text-xs font-semibold text-text-secondary uppercase tracking-wider mb-2">Discovered Services</h4>
              <div className="flex flex-wrap gap-2">
                {analysis.mappings.map((m, i) => (
                  <Badge key={i} variant={m.confidence >= 0.8 ? 'high' : m.confidence >= 0.5 ? 'medium' : 'low'}>
                    {m.source_service} → {m.azure_service}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          <div className="mt-5 flex gap-2">
            <Button onClick={handleReset} variant="secondary" icon={RefreshCw} size="sm">Import Another</Button>
          </div>
        </Card>
      </div>
    );
  }

  // ── Input state ──
  return (
    <div className="space-y-4">
      <Card className="p-6">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-lg bg-cta/15 flex items-center justify-center">
            <FileCode2 className="w-5 h-5 text-cta" />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-text-primary">Import Infrastructure</h3>
            <p className="text-sm text-text-muted">Upload or paste your existing IaC files to generate an Azure mapping.</p>
          </div>
        </div>

        {/* Format selector */}
        <div className="mb-4">
          <label className="block text-xs font-semibold text-text-secondary uppercase tracking-wider mb-2">Format</label>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
            {FORMATS.map((f) => (
              <button
                key={f.id}
                onClick={() => setFormat(f.id)}
                className={`px-3 py-2 rounded-lg border text-left text-xs transition-colors cursor-pointer ${
                  format === f.id
                    ? 'border-cta bg-cta/10 text-cta'
                    : 'border-border bg-secondary/50 text-text-secondary hover:border-border-light'
                }`}
              >
                <span className="font-medium block">{f.label}</span>
              </button>
            ))}
          </div>
        </div>

        {/* File upload / paste */}
        <div className="mb-4">
          <label className="block text-xs font-semibold text-text-secondary uppercase tracking-wider mb-2">Source</label>
          <div className="flex gap-2 mb-2">
            <Button onClick={() => fileRef.current?.click()} variant="secondary" icon={Upload} size="sm">
              Upload File
            </Button>
            <Button onClick={handlePaste} variant="ghost" icon={ClipboardPaste} size="sm">
              Paste from Clipboard
            </Button>
            <input ref={fileRef} type="file" accept=".tf,.tfstate,.json,.yaml,.yml" className="hidden" onChange={handleFileUpload} />
          </div>
          {fileName && (
            <div className="flex items-center gap-2 text-xs text-text-muted mb-2">
              <FileCode2 className="w-3.5 h-3.5" />
              <span>{fileName}</span>
              <button onClick={handleReset} className="text-text-muted hover:text-danger cursor-pointer">
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          )}
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="Or paste your Terraform / CloudFormation / ARM / K8s content here…"
            className="w-full h-48 px-3 py-2 text-xs font-mono bg-surface border border-border rounded-lg resize-y focus:outline-none focus:ring-2 focus:ring-cta/50 text-text-primary placeholder:text-text-muted"
          />
        </div>

        {error && (
          <div className="flex items-center gap-2 text-sm text-danger mb-3">
            <AlertTriangle className="w-4 h-4 shrink-0" />
            {error}
          </div>
        )}

        <Button onClick={handleImport} disabled={!content.trim()} loading={loading} icon={FileCode2}>
          {loading ? 'Importing…' : 'Import & Analyze'}
        </Button>
      </Card>
    </div>
  );
}
