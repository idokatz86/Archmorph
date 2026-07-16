const FORMAT_CONTRACTS = Object.freeze({
  terraform: { mimeType: 'text/plain', extension: '.tf' },
  bicep: { mimeType: 'text/plain', extension: '.bicep' },
  'architecture-package-html': { mimeType: 'text/html', extension: '.html' },
  'architecture-package-svg-primary': { mimeType: 'image/svg+xml', extension: '.svg' },
  'architecture-package-svg-dr': { mimeType: 'image/svg+xml', extension: '.svg' },
  'hld-docx': {
    mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    extension: '.docx',
  },
  'hld-pdf': { mimeType: 'application/pdf', extension: '.pdf' },
  'hld-pptx': {
    mimeType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    extension: '.pptx',
  },
  'cost-csv': { mimeType: 'text/csv', extension: '.csv' },
  'timeline-json': { mimeType: 'application/json', extension: '.json' },
  'timeline-markdown': { mimeType: 'text/markdown', extension: '.md' },
  'timeline-csv': { mimeType: 'text/csv', extension: '.csv' },
  'analysis-report-pdf': { mimeType: 'application/pdf', extension: '.pdf' },
});

function normalizeMimeType(value = '') {
  return value.split(';', 1)[0].trim().toLowerCase();
}

function safeFilename(value, fallback) {
  const leaf = String(value || '').split(/[\\/]/).pop();
  const candidate = Array.from(leaf)
    .filter(character => character.charCodeAt(0) >= 32 && character.charCodeAt(0) !== 127)
    .join('')
    .trim();
  return candidate || fallback;
}

function filenameFromContentDisposition(value) {
  if (!value) return null;

  const encoded = value.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  if (encoded) {
    try {
      return decodeURIComponent(encoded.replace(/^"|"$/g, ''));
    } catch {
      // Fall through to the regular filename parameter.
    }
  }

  return value.match(/filename\s*=\s*"([^"]+)"/i)?.[1]
    || value.match(/filename\s*=\s*([^;]+)/i)?.[1]?.trim()
    || null;
}

export function createArtifactResult({
  blob,
  filename,
  format,
  mimeType,
  exportCapability = null,
  checksum = null,
  provenance = null,
}) {
  const contract = FORMAT_CONTRACTS[format];
  if (!contract) throw new Error(`Unknown artifact format: ${format}`);
  if (!(blob instanceof Blob)) throw new Error(`Artifact ${format} did not produce a Blob`);

  const normalizedMime = normalizeMimeType(mimeType || blob.type);
  if (normalizedMime !== contract.mimeType) {
    throw new Error(`Artifact ${format} expected ${contract.mimeType}, received ${normalizedMime || 'unknown MIME type'}`);
  }

  const normalizedFilename = safeFilename(filename, `archmorph-export${contract.extension}`);
  if (!normalizedFilename.toLowerCase().endsWith(contract.extension)) {
    throw new Error(`Artifact ${format} filename must end with ${contract.extension}`);
  }

  return {
    blob,
    filename: normalizedFilename,
    format,
    mimeType: normalizedMime,
    exportCapability,
    checksum,
    provenance,
  };
}

export function artifactFromText(content, options) {
  const blob = new Blob([content], { type: options.mimeType });
  return createArtifactResult({ ...options, blob });
}

export function artifactFromBase64(content, options) {
  const bytes = Uint8Array.from(atob(content), character => character.charCodeAt(0));
  const blob = new Blob([bytes], { type: options.mimeType });
  return createArtifactResult({ ...options, blob });
}

export async function artifactFromResponse(response, {
  format,
  fallbackFilename,
  provenance,
}) {
  if (!response?.headers?.get || typeof response.blob !== 'function') {
    throw new Error(`Artifact ${format} did not return a downloadable response`);
  }

  const blob = await response.blob();
  const mimeType = normalizeMimeType(response.headers.get('content-type') || blob.type);
  const filename = filenameFromContentDisposition(response.headers.get('content-disposition'));

  return createArtifactResult({
    blob,
    filename: filename || fallbackFilename,
    format,
    mimeType,
    exportCapability: response.headers.get('x-export-capability-next'),
    checksum: response.headers.get('x-artifact-sha256'),
    provenance,
  });
}

export { FORMAT_CONTRACTS };
