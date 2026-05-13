import React, { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Search, ZoomIn, ZoomOut } from 'lucide-react';
import { Button, Modal } from '../ui';

const MIN_ZOOM = 75;
const MAX_ZOOM = 250;
const ZOOM_STEP = 25;
const SMALL_FILE_THRESHOLD_BYTES = 220 * 1024;
const SMALL_PAGE_THRESHOLD_BYTES = 180 * 1024;

function formatKb(size) {
  return `${Math.max(1, Math.round(size / 1024))} KB`;
}

function extractPdfDetails(buffer, fileSize) {
  const decoder = new TextDecoder('latin1');
  const text = decoder.decode(buffer);
  const encrypted = /\/Encrypt\b/.test(text);
  const pagesByType = (text.match(/\/Type\s*\/Page\b/g) || []).length || null;
  const pagesByCount = Number(text.match(/\/Count\s+(\d+)/)?.[1] || 0) || null;
  const pageCount = pagesByCount || pagesByType;

  let legibilityWarning = null;
  if (fileSize <= SMALL_FILE_THRESHOLD_BYTES || (pageCount && (fileSize / pageCount) <= SMALL_PAGE_THRESHOLD_BYTES)) {
    legibilityWarning = 'Potential legibility risk: this PDF is compact and may contain tiny labels or rasterized text. Zoom and inspect before analysis.';
  }

  return { encrypted, pageCount, legibilityWarning };
}

export default function PdfPreviewPanel({ file }) {
  const [previewUrl, setPreviewUrl] = useState(null);
  const [zoom, setZoom] = useState(125);
  const [open, setOpen] = useState(false);
  const [pageCount, setPageCount] = useState(null);
  const [previewError, setPreviewError] = useState(null);
  const [encrypted, setEncrypted] = useState(false);
  const [legibilityWarning, setLegibilityWarning] = useState(null);
  const inlinePreviewSupported = typeof navigator === 'undefined' || navigator.pdfViewerEnabled !== false;

  useEffect(() => {
    if (!file) return undefined;
    let cancelled = false;
    const nextUrl = URL.createObjectURL(file);
    setPreviewUrl(nextUrl);
    setZoom(125);
    setOpen(false);
    setPageCount(null);
    setPreviewError(null);
    setEncrypted(false);
    setLegibilityWarning(null);

    file.arrayBuffer()
      .then((buffer) => {
        if (cancelled) return;
        const details = extractPdfDetails(buffer, file.size);
        setPageCount(details.pageCount);
        setEncrypted(details.encrypted);
        setLegibilityWarning(details.legibilityWarning);
      })
      .catch(() => {
        if (!cancelled) setPreviewError('Could not read this PDF for preview metadata.');
      });

    return () => {
      cancelled = true;
      URL.revokeObjectURL(nextUrl);
    };
  }, [file]);

  const previewSrc = useMemo(() => (
    previewUrl ? `${previewUrl}#page=1&zoom=${zoom}&view=FitH` : null
  ), [previewUrl, zoom]);

  return (
    <section className="rounded-xl border border-border bg-surface/50 p-3 text-left sm:p-4" aria-label="PDF preview section">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-text-primary">PDF Preview</h3>
        <span className="text-xs text-text-muted">{pageCount ? `${pageCount} page${pageCount > 1 ? 's' : ''}` : 'Page count unavailable'} · {formatKb(file.size)}</span>
      </div>

      {legibilityWarning && (
        <p className="mb-2 flex items-start gap-2 rounded-md border border-warning/30 bg-warning/10 px-2 py-1.5 text-xs text-warning" role="status" aria-live="polite">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          {legibilityWarning}
        </p>
      )}

      {(encrypted || previewError || !inlinePreviewSupported) ? (
        <div className="rounded-lg border border-warning/30 bg-warning/10 p-3 text-xs text-warning" role="alert">
          {encrypted
            ? 'Preview unavailable: this PDF appears encrypted/password protected.'
            : previewError
              ? previewError
              : 'Inline PDF preview is not supported in this browser.'}
        </div>
      ) : (
        <>
          <div className="h-64 overflow-hidden rounded-lg border border-border bg-primary sm:h-80">
            {previewSrc && (
              <object data={previewSrc} type="application/pdf" aria-label="First page PDF preview" className="h-full w-full">
                <p className="p-4 text-xs text-text-muted">Inline preview unavailable. Use the inspect action to open the PDF directly.</p>
              </object>
            )}
          </div>
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2" role="group" aria-label="PDF zoom controls">
              <Button type="button" size="sm" variant="ghost" icon={ZoomOut} aria-label="Zoom out PDF preview" disabled={zoom <= MIN_ZOOM} onClick={() => setZoom(z => Math.max(MIN_ZOOM, z - ZOOM_STEP))}>
                Zoom Out
              </Button>
              <span className="text-xs font-medium text-text-secondary" aria-live="polite">{zoom}%</span>
              <Button type="button" size="sm" variant="ghost" icon={ZoomIn} aria-label="Zoom in PDF preview" disabled={zoom >= MAX_ZOOM} onClick={() => setZoom(z => Math.min(MAX_ZOOM, z + ZOOM_STEP))}>
                Zoom In
              </Button>
            </div>
            <Button type="button" size="sm" variant="secondary" icon={Search} onClick={() => setOpen(true)}>
              Open Larger View
            </Button>
          </div>
        </>
      )}

      {previewUrl && (
        <a className="mt-2 inline-flex text-xs text-cta underline-offset-2 hover:underline" href={previewUrl} target="_blank" rel="noreferrer">
          Open PDF in a new tab
        </a>
      )}

      <Modal open={open} onClose={() => setOpen(false)} title="PDF Preview (First Page)" className="max-w-5xl">
        <div className="h-[70vh] overflow-hidden rounded-lg border border-border bg-primary">
          {previewSrc ? <object data={previewSrc} type="application/pdf" aria-label="Large first page PDF preview" className="h-full w-full" /> : null}
        </div>
      </Modal>
    </section>
  );
}
