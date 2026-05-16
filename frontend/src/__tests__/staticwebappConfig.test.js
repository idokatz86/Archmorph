import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { describe, expect, it } from 'vitest';

describe('Static Web App security headers config', () => {
  it('ships CSP and frame protection for the app shell', () => {
    execFileSync('npm', ['run', 'build'], {
      cwd: process.cwd(),
      env: { ...process.env, VITE_API_BASE: process.env.VITE_API_BASE ?? 'https://api.archmorphai.com' },
      stdio: 'pipe',
    });

    const configPaths = [
      path.resolve(process.cwd(), 'public/staticwebapp.config.json'),
      path.resolve(process.cwd(), 'dist/staticwebapp.config.json'),
    ];

    for (const configPath of configPaths) {
      const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
      const csp = config.globalHeaders['Content-Security-Policy'];

      expect(config.globalHeaders['X-Frame-Options']).toBe('DENY');
      expect(config.globalHeaders['Permissions-Policy']).toBe('camera=(), microphone=(), geolocation=()');
      expect(csp).toContain("default-src 'self'");
      expect(csp).toContain("connect-src 'self' https://api.archmorphai.com");
      expect(csp).toContain("img-src 'self' data: blob:");
      expect(csp).toContain("object-src 'none'");
      expect(csp).toContain("frame-ancestors 'none'");
    }
  });
});
