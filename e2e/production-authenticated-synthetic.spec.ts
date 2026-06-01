import { test, expect, type Page } from '@playwright/test';
import path from 'node:path';
import { mkdir, writeFile } from 'node:fs/promises';

const ENABLED = process.env.PRODUCTION_BROWSER_SYNTHETIC === '1';
const FRONTEND_URL = (process.env.FRONTEND_URL || '').replace(/\/$/, '');
const API_BASE = (process.env.API_BASE || '').replace(/\/$/, '');
const ARTIFACT_ROOT = process.env.PRODUCTION_SYNTHETIC_ARTIFACT_ROOT || `smoke-artifacts/production-browser/local`;
const HEALTH_API_KEY = process.env.HEALTH_API_KEY || '';

function requireEnv(name: string, value: string) {
  if (!value) {
    throw new Error(`${name} is required for production browser synthetic`);
  }
}

function runUrl() {
  const server = process.env.GITHUB_SERVER_URL || 'https://github.com';
  const repo = process.env.GITHUB_REPOSITORY || '';
  const runId = process.env.GITHUB_RUN_ID || '';
  return repo && runId ? `${server}/${repo}/actions/runs/${runId}` : null;
}

async function saveJson(relativePath: string, payload: unknown) {
  const fullPath = path.resolve(process.cwd(), ARTIFACT_ROOT, relativePath);
  await mkdir(path.dirname(fullPath), { recursive: true });
  await writeFile(fullPath, JSON.stringify(payload, null, 2), 'utf-8');
}

async function createSyntheticDiagramPng(page: Page, relativePath: string) {
  const fullPath = path.resolve(process.cwd(), ARTIFACT_ROOT, relativePath);
  await mkdir(path.dirname(fullPath), { recursive: true });
  await page.setViewportSize({ width: 900, height: 520 });
  await page.setContent(`
    <html>
      <body style="margin:0;background:#f8fafc;font-family:Arial,sans-serif;">
        <main style="width:900px;height:520px;display:grid;place-items:center;">
          <svg width="820" height="430" viewBox="0 0 820 430" xmlns="http://www.w3.org/2000/svg">
            <rect width="820" height="430" rx="18" fill="#ffffff" stroke="#0f172a" stroke-width="3"/>
            <text x="410" y="52" text-anchor="middle" font-size="28" font-weight="700" fill="#0f172a">AWS Production Synthetic Architecture</text>
            <rect x="70" y="130" width="160" height="88" rx="12" fill="#dbeafe" stroke="#2563eb" stroke-width="3"/>
            <text x="150" y="162" text-anchor="middle" font-size="18" font-weight="700" fill="#1e3a8a">Amazon CloudFront</text>
            <text x="150" y="190" text-anchor="middle" font-size="14" fill="#1e40af">Browser edge traffic</text>
            <rect x="330" y="130" width="160" height="88" rx="12" fill="#dcfce7" stroke="#16a34a" stroke-width="3"/>
            <text x="410" y="162" text-anchor="middle" font-size="18" font-weight="700" fill="#14532d">Amazon API Gateway</text>
            <text x="410" y="190" text-anchor="middle" font-size="14" fill="#166534">Authenticated API</text>
            <rect x="590" y="130" width="160" height="88" rx="12" fill="#fef3c7" stroke="#d97706" stroke-width="3"/>
            <text x="670" y="162" text-anchor="middle" font-size="18" font-weight="700" fill="#78350f">AWS Lambda</text>
            <text x="670" y="190" text-anchor="middle" font-size="14" fill="#92400e">Analyze + export</text>
            <path d="M230 174 H330" stroke="#334155" stroke-width="4" marker-end="url(#arrow)"/>
            <path d="M490 174 H590" stroke="#334155" stroke-width="4" marker-end="url(#arrow)"/>
            <rect x="170" y="285" width="480" height="70" rx="12" fill="#f1f5f9" stroke="#64748b" stroke-width="2"/>
            <text x="410" y="312" text-anchor="middle" font-size="17" font-weight="700" fill="#334155">Amazon S3 + Amazon RDS data tier</text>
            <text x="410" y="338" text-anchor="middle" font-size="14" fill="#475569">Authenticated upload -> AWS analysis -> Draw.io export</text>
            <defs>
              <marker id="arrow" markerWidth="10" markerHeight="10" refX="7" refY="3" orient="auto" markerUnits="strokeWidth">
                <path d="M0,0 L0,6 L8,3 z" fill="#334155"/>
              </marker>
            </defs>
          </svg>
        </main>
      </body>
    </html>
  `);
  await page.screenshot({ path: fullPath, fullPage: true });
  return fullPath;
}

test.describe('Production authenticated browser synthetic', () => {
  test.skip(!ENABLED, 'Production browser synthetic is only enabled in production synthetic workflows.');

  test('verifies SWA bridge, browser analyze path, ownership, and bearer Draw.io export', async ({ page, request }) => {
    requireEnv('FRONTEND_URL', FRONTEND_URL);
    requireEnv('API_BASE', API_BASE);

    const syntheticPrincipal = Buffer.from(
      JSON.stringify({
        identityProvider: 'github',
        userId: process.env.SYNTHETIC_PRINCIPAL_USER_ID || 'prod-synthetic-user',
        userDetails: process.env.SYNTHETIC_PRINCIPAL_EMAIL || 'prod-synthetic@archmorph.test',
        userRoles: ['authenticated'],
        claims: [{ typ: 'name', val: process.env.SYNTHETIC_PRINCIPAL_NAME || 'Production Synthetic' }],
      }),
      'utf-8',
    ).toString('base64');

    let authBridgeMode = 'swa-managed-function';
    let bridgeResponse = await request.post(`${FRONTEND_URL}/api/auth/swa-session`, {
      headers: {
        'x-ms-client-principal': syntheticPrincipal,
        'Content-Type': 'application/json',
      },
      data: {},
    });

    if (!bridgeResponse.ok() && HEALTH_API_KEY) {
      authBridgeMode = 'backend-api-key-fallback';
      bridgeResponse = await request.post(`${API_BASE}/auth/swa-session`, {
        headers: {
          'X-API-Key': HEALTH_API_KEY,
          'Content-Type': 'application/json',
        },
        data: { client_principal: syntheticPrincipal },
      });
    }

    expect(bridgeResponse.ok()).toBeTruthy();
    const bridgeBody = await bridgeResponse.json();
    const sessionToken = bridgeBody?.session_token as string;
    expect(sessionToken).toBeTruthy();

    await page.addInitScript((token: string) => {
      localStorage.setItem('archmorph_session_token', token);
    }, sessionToken);

    const sampleUploadPath = await createSyntheticDiagramPng(page, 'fixtures/production-synthetic-diagram.png');

    await page.goto(`${FRONTEND_URL}/#translator`);
    await expect(page.locator('#root')).toBeVisible({ timeout: 30_000 });

    await page.locator('input[type="file"]').setInputFiles(sampleUploadPath);
    await expect(page.getByText('production-synthetic-diagram.png')).toBeVisible({ timeout: 15_000 });

    const uploadResponsePromise = page.waitForResponse((response) =>
      response.request().method() === 'POST'
      && /\/api\/projects\/[^/]+\/diagrams$/.test(new URL(response.url()).pathname),
    );
    const analyzeAsyncResponsePromise = page.waitForResponse((response) =>
      response.request().method() === 'POST'
      && /\/api\/diagrams\/[^/]+\/analyze-async$/.test(new URL(response.url()).pathname),
    );

    await page.getByRole('button', { name: 'Analyze This Diagram' }).click();

    const uploadResponse = await uploadResponsePromise;
    expect(uploadResponse.ok()).toBeTruthy();
    const uploadBody = await uploadResponse.json();
    const diagramId = uploadBody?.diagram_id as string;
    expect(diagramId).toBeTruthy();

    const analyzeAsyncResponse = await analyzeAsyncResponsePromise;
    let analyzeBody: any = null;
    let latestExportCapability = uploadBody?.export_capability || null;

    if (analyzeAsyncResponse.status() === 202) {
      const queued = await analyzeAsyncResponse.json();
      const statusUrlPath = queued?.status_url as string;
      expect(statusUrlPath).toBeTruthy();

      const statusUrl = new URL(statusUrlPath, API_BASE).toString();
      for (let attempt = 1; attempt <= 60; attempt += 1) {
        const statusResponse = await request.get(statusUrl, {
          headers: { Authorization: `Bearer ${sessionToken}` },
        });
        expect(statusResponse.ok()).toBeTruthy();
        const statusBody = await statusResponse.json();
        if (statusBody?.status === 'completed') {
          analyzeBody = statusBody?.result || null;
          latestExportCapability = analyzeBody?.export_capability || latestExportCapability;
          break;
        }
        if (statusBody?.status === 'failed') {
          throw new Error(`Async analysis failed: ${statusBody?.error || 'unknown error'}`);
        }
        await new Promise((resolve) => setTimeout(resolve, 2_000));
      }
      expect(analyzeBody).toBeTruthy();
    } else {
      const analyzeResponse = await page.waitForResponse((response) =>
        response.request().method() === 'POST'
        && /\/api\/diagrams\/[^/]+\/analyze$/.test(new URL(response.url()).pathname),
      );
      expect(analyzeResponse.ok()).toBeTruthy();
      analyzeBody = await analyzeResponse.json();
      latestExportCapability = analyzeBody?.export_capability || latestExportCapability;
    }

    expect(analyzeBody?._owner_user_id).toBeTruthy();
    expect(analyzeBody?._owner_api_key_id).toBeFalsy();
    expect(latestExportCapability).toBeTruthy();

    await mkdir(path.resolve(process.cwd(), ARTIFACT_ROOT, 'screenshots'), { recursive: true });
    await page.screenshot({ path: path.resolve(process.cwd(), ARTIFACT_ROOT, 'screenshots', 'translator-results.png'), fullPage: true });

    const drawioRequestHeaders = {
      Authorization: `Bearer ${sessionToken}`,
      'X-Export-Capability': latestExportCapability,
      'Content-Type': 'application/json',
    };
    const drawioResponse = await request.post(`${API_BASE}/diagrams/${diagramId}/export-diagram?format=drawio`, {
      headers: {
        ...drawioRequestHeaders,
      },
      data: {},
    });
    expect(drawioResponse.ok()).toBeTruthy();
    const drawioBody = await drawioResponse.json();
    expect(typeof drawioBody?.content).toBe('string');
    expect(drawioBody.content).toContain('<mxfile');

    const healthHeaders = HEALTH_API_KEY
      ? { 'X-API-Key': HEALTH_API_KEY }
      : { Authorization: `Bearer ${sessionToken}` };
    const healthResponse = await request.get(`${API_BASE}/health`, { headers: healthHeaders });
    expect(healthResponse.ok()).toBeTruthy();
    const healthBody = await healthResponse.json();

    const evidence = {
      summary: {
        run_url: runUrl(),
        revision_sha: process.env.GITHUB_SHA || null,
        frontend_url_configured: Boolean(FRONTEND_URL),
        api_base_configured: Boolean(API_BASE),
      },
      checks: {
        auth_bridge_mode: authBridgeMode,
        auth_bridge_http_status: bridgeResponse.status(),
        upload_http_status: uploadResponse.status(),
        analyze_async_http_status: analyzeAsyncResponse.status(),
        drawio_export_http_status: drawioResponse.status(),
        health_http_status: healthResponse.status(),
      },
      assertions: {
        owner_user_id_present: Boolean(analyzeBody?._owner_user_id),
        owner_api_key_absent: !analyzeBody?._owner_api_key_id,
        bearer_used_for_upload: (uploadResponse.request().headers()['authorization'] || '').startsWith('Bearer '),
        bearer_used_for_drawio: drawioRequestHeaders.Authorization.startsWith('Bearer '),
        export_capability_used_for_drawio: Boolean(drawioRequestHeaders['X-Export-Capability']),
      },
      correlation_ids: {
        upload: uploadResponse.headers()['x-correlation-id'] || null,
        analyze_async: analyzeAsyncResponse.headers()['x-correlation-id'] || null,
        drawio_export: drawioResponse.headers()['x-correlation-id'] || null,
        health: healthResponse.headers()['x-correlation-id'] || null,
      },
      response_summaries: {
        upload: {
          diagram_id: diagramId,
          status: uploadBody?.status || null,
        },
        analyze: {
          status: analyzeBody?.status || 'completed',
          owner_user_id: analyzeBody?._owner_user_id || null,
          owner_api_key_id_present: Boolean(analyzeBody?._owner_api_key_id),
        },
        drawio_export: {
          filename: drawioBody?.filename || null,
          content_length: typeof drawioBody?.content === 'string' ? drawioBody.content.length : 0,
        },
        health: {
          status: healthBody?.status || null,
          version: healthBody?.version || null,
        },
      },
    };

    await saveJson('summary.json', evidence);
    await saveJson('responses/upload.json', { diagram_id: diagramId, status: uploadBody?.status || null });
    await saveJson('responses/analyze.json', { owner_user_id: analyzeBody?._owner_user_id || null });
    await saveJson('responses/drawio_export.json', { filename: drawioBody?.filename || null });
    await saveJson('responses/health.json', { status: healthBody?.status || null, version: healthBody?.version || null });
  });
});
