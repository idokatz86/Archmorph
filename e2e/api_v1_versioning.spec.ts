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

test.describe('API v1 Versioning', () => {
  test('GET /api/v1/health mirrors /api/health', async ({ request }) => {
    const original = await request.get(`${API_BASE}/api/health`, { timeout: COLD_START_TIMEOUT });
    const v1 = await request.get(`${API_BASE}/api/v1/health`, { timeout: COLD_START_TIMEOUT });

    expect(v1.ok()).toBeTruthy();
    const origData = await original.json();
    const v1Data = await v1.json();

    expect(v1Data.status).toBe(origData.status);
    expect(v1Data.version).toBe(origData.version);
  });

  test('GET /api/v1/services mirrors /api/services', async ({ request }) => {
    const v1 = await request.get(`${API_BASE}/api/v1/services`, { timeout: API_TIMEOUT });
    expect(v1.ok()).toBeTruthy();
    const data = await v1.json();
    expect(data.total).toBeGreaterThan(300);
  });

  test('GET /api/v1/roadmap returns roadmap data', async ({ request }) => {
    const v1 = await request.get(`${API_BASE}/api/v1/roadmap`, { timeout: API_TIMEOUT });
    expect(v1.ok()).toBeTruthy();
    const data = await v1.json();
    expect(data).toHaveProperty('timeline');
  });

  test('GET /api/v1/contact mirrors /api/contact', async ({ request }) => {
    const v1 = await request.get(`${API_BASE}/api/v1/contact`);
    expect(v1.ok()).toBeTruthy();
    const data = await v1.json();
    expect(data.project).toBe('Archmorph');
  });

  test('GET /api/v1/flags returns feature flags', async ({ request }) => {
    const v1 = await request.get(`${API_BASE}/api/v1/flags`, { timeout: API_TIMEOUT });
    expect(v1.ok()).toBeTruthy();
    const data = await v1.json();
    expect(data).toHaveProperty('flags');
  });

  test('v1 responses include X-API-Version header', async ({ request }) => {
    const resp = await request.get(`${API_BASE}/api/v1/health`, { timeout: COLD_START_TIMEOUT });
    const headers = resp.headers();
    expect(headers['x-api-version']).toBe('v1');
  });

  test('v1 responses include X-API-Deprecated header', async ({ request }) => {
    const resp = await request.get(`${API_BASE}/api/v1/health`, { timeout: COLD_START_TIMEOUT });
    const headers = resp.headers();
    expect(headers['x-api-deprecated']).toBe('false');
  });
});

