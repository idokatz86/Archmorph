# Generated export durable-persistence contract

Authenticated exports are scanned before either PostgreSQL metadata or Blob
bytes are persisted. The scanner is deliberately bounded and fail-closed.

## Locally supported formats

- UTF-8, UTF-16, and other text exports used by the application
- ZIP, DOCX, and PPTX archives, including recursively nested archives
- PDF documents with structural validation and bounded text extraction
- PNG and JPEG images with type, metadata, and pixel-count validation

Archives reject encryption, unsafe paths, excessive member counts, oversized
members/expanded content, excessive compression ratios, excessive nesting, and
opaque members without a configured scanner. Text at every supported layer is
checked for secret-like assignments and known credential formats.

## Unsupported binary formats

Opaque binary formats have no implicit UTF-8 bypass. Authenticated durable
persistence returns `artifact_binary_scan_unavailable` unless that format is
handled by this bounded scanner. Any future external DLP integration must be
implemented inside the scanner boundary with explicit configuration, bounded
timeouts/bytes, deterministic failure behavior, and tests proving that scanner
unavailability prevents both Blob upload and PostgreSQL artifact creation.

## Blob deletion references

Only internal `azblob://<configured-container>/artifacts/...` references emitted
by the application are accepted. Owner and tenant path hashes must match the
durable purge operation. Accounts, containers, URLs, and arbitrary prefixes
supplied by callers are never used as deletion targets. Purge completion
requires confirmed Blob absence; not-found is idempotent and storage errors keep
the durable purge operation pending for retry.