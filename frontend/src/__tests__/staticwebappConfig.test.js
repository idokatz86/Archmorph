import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { describe, expect, it } from 'vitest';

function parseCspDirectives(csp) {
  return Object.fromEntries(
    csp
      .split(';')
      .map((directive) => directive.trim().split(/\s+/))
      .filter(([name]) => Boolean(name))
      .map(([name, ...sources]) => [name, sources]),
  );
}

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
      const directives = parseCspDirectives(csp);
      const fallbackExcludes = config.navigationFallback?.exclude || [];

      expect(config.globalHeaders['X-Frame-Options']).toBe('DENY');
      expect(config.globalHeaders['Permissions-Policy']).toBe('camera=(), microphone=(), geolocation=()');
      expect(config.platform?.apiRuntime).toBe('node:20');
      expect(fallbackExcludes).toEqual(expect.arrayContaining(['/api/*', '/.auth/*']));
      expect(directives['default-src']).toContain("'self'");
      expect(directives['connect-src']).toEqual(expect.arrayContaining(["'self'", 'https://api.archmorphai.com']));
      expect(directives['img-src']).toEqual(expect.arrayContaining(["'self'", 'data:', 'blob:']));
      expect(directives['object-src']).toContain("'none'");
      expect(directives['frame-ancestors']).toContain("'none'");
      expect(directives['style-src']).toContain('https://fonts.googleapis.com');
      expect(directives['font-src']).toEqual(expect.arrayContaining(["'self'", 'https://fonts.gstatic.com']));
    }
  });
});
