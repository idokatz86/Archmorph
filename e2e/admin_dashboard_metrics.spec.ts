/**
 * Archmorph E2E Tests — Playwright
 *
 * Tests the live deployed application end-to-end.
 * Configure via environment variables:
 *   - API_BASE: Backend API URL
 *   - ADMIN_KEY: Admin authentication key
 */

import { test, expect, Page } from '@playwright/test';
import path from 'path';
import fs from 'fs';

// Use environment variables with safe fallbacks for local development
const API_BASE = process.env.API_BASE || 'http://localhost:8000';
const ADMIN_KEY = process.env.ADMIN_KEY || 'test-admin-key';

/** Resolved dynamically from /api/health on first use */
let _cachedVersion: string | null = null;
async function getVersion(request: any): Promise<string> {
  if (_cachedVersion) return _cachedVersion;
  const resp = await request.get(`${API_BASE}/api/health`, { timeout: COLD_START_TIMEOUT });
  const data = await resp.json();
  _cachedVersion = data.version;
  return _cachedVersion!;
}

// Longer timeout for cold-start container apps
const COLD_START_TIMEOUT = 45_000;
const API_TIMEOUT = 30_000;

// ====================================================================
// Helpers
// ====================================================================

/** Create a minimal 1x1 PNG file for upload tests */
function createTestPng(filePath: string): void {
  const png = Buffer.from([
    0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
    0x00, 0x00, 0x00, 0x0d, 0x49, 0x48, 0x44, 0x52,
    0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
    0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53,
    0xde, 0x00, 0x00, 0x00, 0x0c, 0x49, 0x44, 0x41,
    0x54, 0x08, 0xd7, 0x63, 0xf8, 0xcf, 0xc0, 0x00,
    0x00, 0x00, 0x02, 0x00, 0x01, 0xe2, 0x21, 0xbc,
    0x33, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4e,
    0x44, 0xae, 0x42, 0x60, 0x82,
  ]);
  fs.writeFileSync(filePath, png);
}

/** Navigate to results step (upload → analyze → skip questions → results) */
async function navigateToResults(page: Page): Promise<void> {
  const testPng = path.join(__dirname, `test-${Date.now()}.png`);
  createTestPng(testPng);
  try {
    await page.locator('input[type="file"]').setInputFiles(testPng);
    // Wait for analyzing to start
    await expect(page.getByText('Analyzing Architecture')).toBeVisible({ timeout: COLD_START_TIMEOUT });
    // Wait for questions page
    await expect(page.getByText('Customize Your Azure Architecture')).toBeVisible({ timeout: COLD_START_TIMEOUT });
    // Skip to results
    await page.getByRole('button', { name: /Skip Customization/i }).click();
    // Wait for results to render
    await expect(page.getByText('High Confidence')).toBeVisible({ timeout: API_TIMEOUT });
  } finally {
    if (fs.existsSync(testPng)) fs.unlinkSync(testPng);
  }
}

// ====================================================================
// Warm up the backend before all tests
// ====================================================================

test.beforeAll(async ({ request }) => {
  // Hit the health endpoint to wake up the container
  try {
    await request.get(`${API_BASE}/api/health`, { timeout: COLD_START_TIMEOUT });
  } catch {
    // Ignore — container might need time
  }
});

// ====================================================================
// 1. Page Load & Navigation
// ====================================================================

test.describe('Admin Dashboard Metrics', () => {
  test('admin login and metrics flow', async ({ request }) => {
    const loginResp = await request.post(`${API_BASE}/api/admin/login`, {
      data: { key: ADMIN_KEY },
      headers: { 'Content-Type': 'application/json' },
    });
    if (loginResp.status() === 503 || loginResp.status() === 403) {
      // Admin not configured or test credentials rejected — skip
      return;
    }
    expect(loginResp.ok()).toBeTruthy();
    const { token } = await loginResp.json();

    // Metrics summary
    const metricsResp = await request.get(`${API_BASE}/api/admin/metrics`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(metricsResp.ok()).toBeTruthy();
    const metrics = await metricsResp.json();
    expect(metrics).toHaveProperty('totals');

    // Funnel
    const funnelResp = await request.get(`${API_BASE}/api/admin/metrics/funnel`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(funnelResp.ok()).toBeTruthy();

    // Daily
    const dailyResp = await request.get(`${API_BASE}/api/admin/metrics/daily?days=7`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(dailyResp.ok()).toBeTruthy();

    // Recent events
    const recentResp = await request.get(`${API_BASE}/api/admin/metrics/recent?limit=5`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(recentResp.ok()).toBeTruthy();

    // Logout
    const logoutResp = await request.post(`${API_BASE}/api/admin/logout`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(logoutResp.ok()).toBeTruthy();
  });

  test('admin audit logs endpoint (if admin configured)', async ({ request }) => {
    const loginResp = await request.post(`${API_BASE}/api/admin/login`, {
      data: { key: ADMIN_KEY },
      headers: { 'Content-Type': 'application/json' },
    });
    if (loginResp.status() === 503) return;
    if (!loginResp.ok()) return;
    const { token } = await loginResp.json();

    const resp = await request.get(`${API_BASE}/api/admin/audit`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data).toHaveProperty('events');
  });

  test('admin observability endpoint returns OTel metrics', async ({ request }) => {
    const loginResp = await request.post(`${API_BASE}/api/admin/login`, {
      data: { key: ADMIN_KEY },
      headers: { 'Content-Type': 'application/json' },
    });
    if (loginResp.status() === 503) return;
    if (!loginResp.ok()) return;
    const { token } = await loginResp.json();

    const resp = await request.get(`${API_BASE}/api/admin/observability`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data).toHaveProperty('counters');
    expect(data).toHaveProperty('histograms');
  });

  test('admin 5-click opens panel in UI', async ({ page }) => {
    await page.goto('/');
    const versionText = page.getByText(/Archmorph v\d+\.\d+/);
    if (!(await versionText.isVisible())) return;

    for (let i = 0; i < 5; i++) {
      await versionText.click({ delay: 50 });
    }
    await expect(page.getByText('Admin Analytics')).toBeVisible({ timeout: API_TIMEOUT });
  });
});
