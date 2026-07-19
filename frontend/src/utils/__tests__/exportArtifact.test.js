import { describe, expect, it } from 'vitest';
import {
  artifactFromBase64,
  artifactFromResponse,
  artifactFromText,
  createArtifactResult,
} from '../exportArtifact';

function response(body, { contentType, filename, nextCapability = null, checksum = null } = {}) {
  const headers = new Headers({
    'content-type': contentType,
    'content-disposition': `attachment; filename="${filename}"`,
  });
  if (nextCapability) headers.set('x-export-capability-next', nextCapability);
  if (checksum) headers.set('x-artifact-sha256', checksum);
  return new Response(body, { status: 200, headers });
}

describe('exportArtifact contract', () => {
  it('normalizes a streamed CSV response with filename, provenance, and rotated capability', async () => {
    const result = await artifactFromResponse(
      response('Service,Monthly Low\nTOTAL,10\n', {
        contentType: 'text/csv; charset=utf-8',
        filename: 'cost-estimate-diag.csv',
        nextCapability: 'next-token',
        checksum: 'a'.repeat(64),
      }),
      {
        format: 'cost-csv',
        fallbackFilename: 'fallback.csv',
        provenance: { endpoint: '/cost-estimate/export', source: 'backend' },
      },
    );

    expect(result).toMatchObject({
      filename: 'cost-estimate-diag.csv',
      format: 'cost-csv',
      mimeType: 'text/csv',
      exportCapability: 'next-token',
      checksum: 'a'.repeat(64),
      provenance: { endpoint: '/cost-estimate/export', source: 'backend' },
    });
    expect(await result.blob.text()).toContain('TOTAL,10');
  });

  it('creates validated text and base64 artifacts', async () => {
    const html = artifactFromText('<!doctype html><title>Package</title>', {
      filename: 'package.html',
      format: 'architecture-package-html',
      mimeType: 'text/html',
    });
    const pdf = artifactFromBase64(btoa('%PDF-1.7\n'), {
      filename: 'report.pdf',
      format: 'analysis-report-pdf',
      mimeType: 'application/pdf',
    });

    expect(await html.blob.text()).toContain('<title>Package</title>');
    expect(await pdf.blob.text()).toMatch(/^%PDF-/);
  });

  it('rejects MIME and filename mismatches', () => {
    expect(() => createArtifactResult({
      blob: new Blob(['not a PDF'], { type: 'text/markdown' }),
      filename: 'cost-estimate.md',
      format: 'analysis-report-pdf',
      mimeType: 'text/markdown',
    })).toThrow(/expected application\/pdf/i);

    expect(() => artifactFromText('csv', {
      filename: 'cost-estimate.pdf',
      format: 'cost-csv',
      mimeType: 'text/csv',
    })).toThrow(/must end with \.csv/i);
  });
});
