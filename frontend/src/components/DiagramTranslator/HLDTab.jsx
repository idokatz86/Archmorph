import React from 'react';
import { Loader2, RefreshCw, ArrowLeft, ArrowRight } from 'lucide-react';
import { Button, Card } from '../ui';
import HLDPanel from './HLDPanel';

/**
 * HLD Tab — standalone step in the 7-step workflow (#400).
 * Auto-generates HLD when the user reaches this tab.
 */
export default function HLDTab({
  hldData, hldLoading, hldTab, hldExportLoading, hldIncludeDiagrams,
  copyFeedback, error,
  onGenerateHld, onSetHldTab, onSetHldIncludeDiagrams, onHldExport,
  onCopyWithFeedback, onSetStep,
}) {
  return (
    <div className="space-y-6">
      {/* Loading state */}
      {hldLoading && !hldData && (
        <Card className="p-12">
          <div className="flex flex-col items-center justify-center gap-4">
            <Loader2 className="w-10 h-10 text-cta animate-spin" />
            <div className="text-center">
              <h2 className="text-lg font-bold text-text-primary mb-1">Generating High-Level Design</h2>
              <p className="text-sm text-text-muted max-w-md">
                Our AI is creating a comprehensive architecture document covering services,
                networking, security, migration strategy, and WAF alignment...
              </p>
            </div>
            <div className="w-64 h-2 bg-secondary rounded-full overflow-hidden mt-2">
              <div className="h-full bg-cta/60 rounded-full animate-pulse" style={{ width: '60%' }} />
            </div>
            <p className="text-xs text-text-muted">This typically takes 30-60 seconds</p>
          </div>
        </Card>
      )}

      {/* HLD Content */}
      {hldData && (
        <>
          <HLDPanel
            hldData={hldData}
            hldTab={hldTab}
            hldExportLoading={hldExportLoading}
            hldIncludeDiagrams={hldIncludeDiagrams}
            copyFeedback={copyFeedback}
            onSetHldTab={onSetHldTab}
            onSetHldIncludeDiagrams={onSetHldIncludeDiagrams}
            onHldExport={onHldExport}
            onCopyWithFeedback={onCopyWithFeedback}
          />
          <div className="flex items-center justify-between">
            <Button onClick={onGenerateHld} variant="ghost" icon={RefreshCw} loading={hldLoading}>
              Regenerate HLD
            </Button>
          </div>
        </>
      )}

      {/* Error state — no HLD */}
      {!hldLoading && !hldData && error && (
        <Card className="p-8 text-center">
          <p className="text-sm text-danger mb-4">HLD generation failed. Please try again.</p>
          <Button onClick={onGenerateHld} variant="primary" icon={RefreshCw}>
            Retry HLD Generation
          </Button>
        </Card>
      )}

      {/* No error, not loading, no data — first visit trigger */}
      {!hldLoading && !hldData && !error && (
        <Card className="p-8 text-center">
          <p className="text-sm text-text-muted mb-4">Preparing HLD generation...</p>
          <Loader2 className="w-6 h-6 text-cta animate-spin mx-auto" />
        </Card>
      )}

      {/* Navigation */}
      <div className="flex items-center justify-between">
        <Button onClick={() => onSetStep('iac')} variant="ghost" icon={ArrowLeft}>
          Back to IaC Code
        </Button>
        <Button onClick={() => onSetStep('pricing')} variant="primary" icon={ArrowRight}>
          View Pricing
        </Button>
      </div>
    </div>
  );
}
