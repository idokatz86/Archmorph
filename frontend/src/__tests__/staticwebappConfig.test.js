import fs from 'node:fs';
import path from 'node:path';

describe('Static Web App security headers config', () => {
  it('ships CSP and frame protection for the app shell', () => {
    const configPath = path.resolve(process.cwd(), 'public/staticwebapp.config.json');
    const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
    const csp = config.globalHeaders['Content-Security-Policy'];

    expect(config.globalHeaders['X-Frame-Options']).toBe('DENY');
    expect(csp).toContain("default-src 'self'");
    expect(csp).toContain("connect-src 'self' https://api.archmorphai.com");
    expect(csp).toContain("img-src 'self' data: blob:");
    expect(csp).toContain("object-src 'self' blob:");
    expect(csp).toContain("frame-ancestors 'none'");
  });
});
