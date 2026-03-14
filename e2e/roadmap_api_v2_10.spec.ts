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

test.describe('Roadmap API (v2.10)', () => {
  test('roadmap endpoint returns timeline', async ({ request }) => {
    const resp = await request.get(`${API_BASE}/api/roadmap`);
    expect(resp.ok()).toBeTruthy();

    const data = await resp.json();
    expect(data).toHaveProperty('timeline');
    expect(data.timeline).toHaveProperty('released');
    expect(data.timeline).toHaveProperty('in_progress');
    expect(data.timeline).toHaveProperty('planned');
    expect(data.timeline).toHaveProperty('ideas');
  });

  test('roadmap includes statistics', async ({ request }) => {
    const resp = await request.get(`${API_BASE}/api/roadmap`);
    const data = await resp.json();
    
    expect(data).toHaveProperty('stats');
    expect(data.stats).toHaveProperty('total_releases');
    expect(data.stats).toHaveProperty('features_shipped');
    expect(data.stats).toHaveProperty('days_since_launch');
    expect(data.stats).toHaveProperty('current_version');
  });

  test('roadmap has v1.0.0 as first release', async ({ request }) => {
    const resp = await request.get(`${API_BASE}/api/roadmap`);
    const data = await resp.json();
    
    const versions = data.timeline.released.map((r: any) => r.version);
    expect(versions).toContain('1.0.0');
  });

  test('roadmap release endpoint returns specific version', async ({ request }) => {
    const resp = await request.get(`${API_BASE}/api/roadmap/release/2.9.0`);
    expect(resp.ok()).toBeTruthy();

    const data = await resp.json();
    expect(data.version).toBe('2.9.0');
    expect(data.name).toBeDefined();
  });

  test('roadmap release returns 404 for unknown version', async ({ request }) => {
    const resp = await request.get(`${API_BASE}/api/roadmap/release/99.99.99`);
    expect(resp.status()).toBe(404);
  });

  test('feature request endpoint requires valid data', async ({ request }) => {
    const resp = await request.post(`${API_BASE}/api/roadmap/feature-request`, {
      data: { title: 'x', description: 'y' }, // Too short
      headers: { 'Content-Type': 'application/json' },
    });
    expect(resp.status()).toBe(422); // Validation error
  });

  test('bug report endpoint requires valid data', async ({ request }) => {
    const resp = await request.post(`${API_BASE}/api/roadmap/bug-report`, {
      data: { title: 'x', description: 'y' }, // Too short
      headers: { 'Content-Type': 'application/json' },
    });
    expect(resp.status()).toBe(422); // Validation error
  });
});

