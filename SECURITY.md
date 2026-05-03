# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 2.12.x  | :white_check_mark: |
| 2.11.x  | :white_check_mark: |
| 2.10.x  | :white_check_mark: |
| 2.9.x   | :white_check_mark: |
| < 2.9   | :x:                |

## Reporting a Vulnerability

We take security seriously. If you discover a security vulnerability, please report it responsibly.

### How to Report

1. **DO NOT** create a public GitHub issue for security vulnerabilities
2. Use GitHub's private vulnerability reporting feature at: **https://github.com/idokatz86/Archmorph/security/advisories/new**
3. Include the following information:
   - Type of vulnerability
   - Full paths of affected source files
   - Location of the affected code (tag/branch/commit)
   - Step-by-step instructions to reproduce
   - Proof-of-concept or exploit code (if possible)
   - Impact assessment

### What to Expect

- **Acknowledgment**: Within 48 hours of your report
- **Initial Assessment**: Within 7 days
- **Resolution Timeline**: Depends on severity
  - Critical: 24-72 hours
  - High: 7 days
  - Medium: 30 days
  - Low: 90 days

### Security Measures in Place

#### Application Security
- **Security Headers**: X-Content-Type-Options, X-Frame-Options, HSTS, Referrer-Policy
- **CORS**: Strict origin allowlist (no wildcards)
- **Rate Limiting**: Per-endpoint rate limits to prevent abuse
- **Input Validation**: Pydantic models for all API inputs
- **File Upload**: Type validation, size limits (25MB max)
- **Authentication**: Azure AD B2C and GitHub OAuth with secure session tokens
- **Authorization**: API key authentication for protected endpoints
- **Timing-Safe Comparison**: `secrets.compare_digest()` for all key verification

#### Infrastructure Security
- **TLS 1.2+**: Enforced on all Azure resources
- **Key Vault**: All secrets stored in Azure Key Vault
- **Managed Identity**: Used for Azure resource access (no credentials in code)
- **Network Security**: Private endpoints, NSGs, VNet integration for production
- **Encryption**: Data at rest and in transit encryption enabled
- **RBAC**: Azure role-based access control for all resources

#### Code Security
- **Dependabot**: Automated dependency updates for all ecosystems
- **Bandit**: Python security linting in CI
- **npm audit**: JavaScript vulnerability scanning in CI
- **pip-audit**: Python dependency vulnerability scanning
- **SVG Sanitization**: XSS protection for icon uploads
- **ZIP Slip Prevention**: Path traversal protection for file uploads

#### Monitoring
- **Azure Application Insights**: Real-time monitoring and alerting
- **Log Analytics**: Centralized logging with audit trails
- **Diagnostic Settings**: Enabled on all Azure resources
- **E2E Health Monitoring**: GitHub Actions workflow with auto-issue creation

## Threat surface: Azure Landing-Zone-SVG pipeline

The landing-zone-svg pipeline (issue #571 → #586) ingests untrusted PDFs / images, vendor icon ZIPs, and LLM-generated content; the rendered SVG is returned to the user. Pre-GA threat-model review for this pipeline lives at [`docs/security/landing_zone_threat_model.md`](docs/security/landing_zone_threat_model.md) (#596).

Headline controls in place:

- **Export/download capability boundary**: generated artifact routes (`export-diagram`, `export-architecture-package`, `export-hld`, and report download) require a one-time `X-Export-Capability` token scoped to the specific `diagram_id`. Tokens are opaque, stored only as SHA-256 digests, expire after 15 minutes by default, are consumed on use to block replay, and rotate after each successful export. Local development may explicitly opt out with `ARCHMORPH_EXPORT_CAPABILITY_REQUIRED=false`; production and staging fail closed.
- **XML output is escape-on-render**: every text run goes through `_xml_escape()` which strips invalid XML chars and escapes the 5 XML entities ([backend/azure_landing_zone.py](backend/azure_landing_zone.py)).
- **Icon-pack writes are authenticated and sanitized**: `POST /api/icon-packs` and `DELETE /api/icon-packs/{pack_id}` require `X-API-Key`, production/staging deployments fail closed if `ARCHMORPH_API_KEY` is missing, uploaded SVGs are parsed with `defusedxml`, scripts/events/style blocks/external references are stripped, and the in-memory icon registry is bounded.
- **Icons are embedded as `data:image/svg+xml;base64` data URIs only** — there is no path to inject `javascript:` or external `http(s):` URIs into a rendered `<image href="…"/>`. Icon bytes come from the server-controlled icon registry.
- **PII boundary**: the retention pipeline (#580) and LZ render path do not import each other; verified via grep in CI.
- **Vision analyzer**: native multimodal — the system prompt is hardcoded, the user message contains only the image, and the response is constrained to a JSON schema with downstream Pydantic validation. `prompt_guard.PROMPT_ARMOR` reinforces the schema constraint.

Open follow-ups (filed as separate issues, see threat-model §5):

- **F-3 (P1)** — mitigated: icon-pack upload and delete routes require `Depends(verify_api_key)`, uploaded SVGs are sanitized before registry insertion, production/staging auth fails closed when the API key is missing, and the registry has bounded in-memory capacity.

P2 findings (webhook SSRF private-IP gap, unbounded analysis size, Pydantic `extra="forbid"`) are tracked but do not block GA.

## Security Best Practices for Contributors

1. **Never commit secrets**: Use environment variables or Key Vault
2. **Validate all inputs**: Use Pydantic models for API inputs (prefer `model_config = ConfigDict(extra="forbid")` on user-facing schemas)
3. **Use parameterized queries**: Prevent SQL injection
4. **Sanitize outputs**: Prevent XSS in frontend; on the SVG renderer, run every text run through `_xml_escape` and only embed icons via `data:image/svg+xml;base64,…`
5. **Keep dependencies updated**: Monitor Dependabot PRs
6. **Follow principle of least privilege**: Minimal permissions for all operations
7. **Capability URLs** must be at least 122 bits of entropy (`secrets.token_urlsafe(16)` or full UUIDv4 — never truncated)
8. **Artifact export endpoints** must validate `X-Export-Capability`, scope it to the requested `diagram_id`, consume it on use, issue a fresh token on success, and audit denial reasons without logging raw token values.

## Acknowledgments

We appreciate responsible disclosure and will acknowledge security researchers who report valid vulnerabilities.
