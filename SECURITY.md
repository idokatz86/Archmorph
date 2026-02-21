# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 2.9.x   | :white_check_mark: |
| 2.8.x   | :white_check_mark: |
| 2.7.x   | :x:                |
| < 2.7   | :x:                |

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

## Security Best Practices for Contributors

1. **Never commit secrets**: Use environment variables or Key Vault
2. **Validate all inputs**: Use Pydantic models for API inputs
3. **Use parameterized queries**: Prevent SQL injection
4. **Sanitize outputs**: Prevent XSS in frontend
5. **Keep dependencies updated**: Monitor Dependabot PRs
6. **Follow principle of least privilege**: Minimal permissions for all operations

## Acknowledgments

We appreciate responsible disclosure and will acknowledge security researchers who report valid vulnerabilities.
