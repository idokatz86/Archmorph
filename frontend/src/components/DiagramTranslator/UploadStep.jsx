import React from 'react';
import { Upload, FileText, X, Building2, Globe2, Boxes, Network, ShieldAlert, LogIn } from 'lucide-react';
import { Badge, Button, Card } from '../ui';
import { ContextualHint } from '../ContextualHint';

const SAMPLES = [
  { id: 'aws-hub-spoke', name: 'Hub & Spoke', icon: Building2, desc: 'Secure Landing Zone', provider: 'aws' },
  { id: 'aws-iaas', name: 'Classic Web App', icon: Globe2, desc: 'Basic 3-tier Architecture', provider: 'aws' },
  { id: 'aws-eks', name: 'Microservices', icon: Boxes, desc: 'EKS Containerized App', provider: 'aws' },
  { id: 'gcp-gke', name: 'GKE Cluster', icon: Network, desc: 'Scalable K8s Platform', provider: 'gcp' }
];

export default function UploadStep({
  dragOver, selectedFile, filePreviewUrl, fileInputRef,
  onDragOver, onDragLeave, onDrop, onFileSelect, onUpload, onRemoveFile, onLoadSample,
  isAuthenticated = true,
  onSignIn,
}) {
  return (
    <Card className="p-12">
      <div className="text-center max-w-lg mx-auto">
        <div className="mb-4 rounded-xl border border-warning/30 bg-warning/5 p-4 text-left">
          <div className="mb-2 flex items-center gap-2 text-warning">
            <ShieldAlert className="h-4 w-4" aria-hidden="true" />
            <p className="text-xs font-semibold uppercase tracking-wide">Confidential Upload Disclosure</p>
          </div>
          <ul className="space-y-1 text-xs text-text-secondary">
            <li>• Files are uploaded for analysis/model processing only and are not used by Archmorph for model training.</li>
            <li>• Server-side upload/session/project/export data uses a 2-hour retention window by default.</li>
            <li>• Browser sessionStorage may keep cached analysis for session-recovery until tab/session close.</li>
            <li>• After analysis completes, a <strong>Purge Current Analysis</strong> option is available to immediately delete uploaded bytes and derived artifacts.</li>
          </ul>
        </div>

        {/* Drag & Drop Zone */}
        <ContextualHint id="upload-prompt" content="Drop any cloud diagram here — or try a sample below" position="bottom">
        <div
          {...(!selectedFile && {
            role: 'button',
            tabIndex: 0,
            'aria-label': 'Upload architecture diagram. Press Enter to browse files.',
            onKeyDown: (e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                fileInputRef.current?.click();
              }
            },
            onClick: () => fileInputRef.current?.click(),
          })}
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onDrop={onDrop}
          className={`relative rounded-2xl border-2 border-dashed p-8 mb-6 transition-all duration-200 ${
            dragOver
              ? 'border-cta bg-cta/10 scale-[1.02] drop-zone-glow'
              : selectedFile
                ? 'border-cta/40 bg-cta/5'
                : 'border-border hover:border-cta/40 hover:bg-secondary/50 cursor-pointer'
          }`}
        >
          {/* File preview */}
          {selectedFile ? (
            <div className="space-y-3">
              {filePreviewUrl ? (
                <img src={filePreviewUrl} alt="Preview" className="max-h-40 mx-auto rounded-lg border border-border object-contain" />
              ) : (
                <div className="w-16 h-16 rounded-2xl bg-cta/10 flex items-center justify-center mx-auto">
                  <FileText className="w-8 h-8 text-cta" />
                </div>
              )}
              <div>
                <p className="text-sm font-medium text-text-primary">{selectedFile.name}</p>
                <p className="text-xs text-text-muted">{(selectedFile.size / 1024).toFixed(0)} KB</p>
              </div>
              <div className="flex items-center justify-center gap-2" data-testid="file-action-buttons">
                {isAuthenticated ? (
                  <Button onClick={(e) => { e.stopPropagation(); onUpload(selectedFile); }} variant="primary" size="md" icon={Upload}>
                    Analyze This Diagram
                  </Button>
                ) : (
                  <Button onClick={(e) => { e.stopPropagation(); onSignIn?.(); }} variant="primary" size="md" icon={LogIn}>
                    Sign in to analyze
                  </Button>
                )}
                <Button onClick={(e) => { e.stopPropagation(); onRemoveFile(); }} variant="ghost" size="sm" icon={X}>
                  Remove
                </Button>
                <Button onClick={(e) => { e.stopPropagation(); fileInputRef.current?.click(); }} variant="ghost" size="sm">
                  Replace file
                </Button>
              </div>
            </div>
          ) : (
            <>
              <div className="w-16 h-16 rounded-2xl bg-cta/10 flex items-center justify-center mx-auto mb-4">
                <Upload className="w-8 h-8 text-cta" />
              </div>
              <h2 className="text-2xl font-bold text-text-primary mb-2">Upload Architecture Diagram</h2>
              <p className="text-sm text-text-secondary mb-4">
                Drag & drop your AWS or GCP diagram here, or click to browse
              </p>
              <p className="text-xs text-text-muted">Supports PNG, JPG, JPEG, SVG, PDF, Draw.io, Visio — up to 10 MB</p>
              {dragOver && (
                <div className="absolute inset-0 rounded-2xl bg-cta/10 flex items-center justify-center">
                  <p className="text-lg font-bold text-cta">Drop diagram here</p>
                </div>
              )}
            </>
          )}
        </div>

        </ContextualHint>

        <input ref={fileInputRef} type="file" accept=".png,.jpg,.jpeg,.svg,.pdf,.vsdx,.drawio,image/png,image/jpeg,image/svg+xml,application/pdf" onChange={e => e.target.files[0] && onFileSelect(e.target.files[0])} className="hidden" aria-label="Select architecture diagram file" />

        {/* Sample Diagrams */}
        <div className="mt-6 pt-6 border-t border-border">
          <p className="text-sm text-text-secondary mb-4">Or try with a sample architecture:</p>
          <div className="grid grid-cols-2 gap-3">
            {SAMPLES.map(sample => (
              <SampleButton key={sample.id} sample={sample} onLoadSample={onLoadSample} />
            ))}
          </div>
        </div>
      </div>
    </Card>
  );
}

function SampleButton({ sample, onLoadSample }) {
  const SampleIcon = sample.icon;
  return (
    <button
      onClick={() => onLoadSample(sample)}
      className={`p-3 rounded-lg bg-secondary hover:bg-secondary/80 transition-all text-left cursor-pointer border border-border hover:scale-[1.02] ${
        sample.provider === 'gcp' ? 'hover:border-[#EA4335]/50' : 'hover:border-[#FF9900]/50'
      }`}
    >
      <div className="flex items-center gap-2">
        <span className="w-7 h-7 rounded-md bg-surface/70 flex items-center justify-center">
          <SampleIcon className="w-4 h-4 text-cta" aria-hidden="true" />
        </span>
        <Badge variant={sample.provider}>{sample.provider.toUpperCase()}</Badge>
      </div>
      <p className="text-sm font-medium text-text-primary mt-1.5">{sample.name}</p>
      <p className="text-xs text-text-muted">{sample.desc}</p>
    </button>
  );
}
