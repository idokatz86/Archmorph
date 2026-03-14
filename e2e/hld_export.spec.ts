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

test.describe('HLD Export', () => {
  test('export-hld endpoint rejects invalid format', async ({ request }) => {
    // Upload + Analyze + Generate HLD first
    const png = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, ...Array(50).fill(0)]);
    const uploadResp = await request.post(`${API_BASE}/api/projects/e2e-hld-export/diagrams`, {
      multipart: {
        file: { name: 'test.png', mimeType: 'image/png', buffer: png },
      },
      timeout: API_TIMEOUT,
    });
    const { diagram_id } = await uploadResp.json();
    await request.post(`${API_BASE}/api/diagrams/${diagram_id}/analyze`, { timeout: API_TIMEOUT });
    await request.post(`${API_BASE}/api/diagrams/${diagram_id}/generate-hld`, { timeout: API_TIMEOUT });

    // Try invalid format
    const resp = await request.post(`${API_BASE}/api/diagrams/${diagram_id}/export-hld?format=xyz`);
    expect(resp.status()).toBe(400);
  });

  test('export-hld DOCX returns content', async ({ request }) => {
    const png = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, ...Array(50).fill(0)]);
    const uploadResp = await request.post(`${API_BASE}/api/projects/e2e-hld-docx/diagrams`, {
      multipart: {
        file: { name: 'test.png', mimeType: 'image/png', buffer: png },
      },
      timeout: API_TIMEOUT,
    });
    const { diagram_id } = await uploadResp.json();
    await request.post(`${API_BASE}/api/diagrams/${diagram_id}/analyze`, { timeout: API_TIMEOUT });
    await request.post(`${API_BASE}/api/diagrams/${diagram_id}/generate-hld`, { timeout: API_TIMEOUT });

    const resp = await request.post(`${API_BASE}/api/diagrams/${diagram_id}/export-hld?format=docx`, { timeout: API_TIMEOUT });
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data).toHaveProperty('content');
    expect(data.format).toBe('docx');
  });

  test('export-hld PDF returns content', async ({ request }) => {
    const png = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, ...Array(50).fill(0)]);
    const uploadResp = await request.post(`${API_BASE}/api/projects/e2e-hld-pdf/diagrams`, {
      multipart: {
        file: { name: 'test.png', mimeType: 'image/png', buffer: png },
      },
      timeout: API_TIMEOUT,
    });
    const { diagram_id } = await uploadResp.json();
    await request.post(`${API_BASE}/api/diagrams/${diagram_id}/analyze`, { timeout: API_TIMEOUT });
    await request.post(`${API_BASE}/api/diagrams/${diagram_id}/generate-hld`, { timeout: API_TIMEOUT });

    const resp = await request.post(`${API_BASE}/api/diagrams/${diagram_id}/export-hld?format=pdf`, { timeout: API_TIMEOUT });
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data).toHaveProperty('content');
    expect(data.format).toBe('pdf');
  });

  test('export-hld PPTX returns content', async ({ request }) => {
    const png = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, ...Array(50).fill(0)]);
    const uploadResp = await request.post(`${API_BASE}/api/projects/e2e-hld-pptx/diagrams`, {
      multipart: {
        file: { name: 'test.png', mimeType: 'image/png', buffer: png },
      },
      timeout: API_TIMEOUT,
    });
    const { diagram_id } = await uploadResp.json();
    await request.post(`${API_BASE}/api/diagrams/${diagram_id}/analyze`, { timeout: API_TIMEOUT });
    await request.post(`${API_BASE}/api/diagrams/${diagram_id}/generate-hld`, { timeout: API_TIMEOUT });

    const resp = await request.post(`${API_BASE}/api/diagrams/${diagram_id}/export-hld?format=pptx`, { timeout: API_TIMEOUT });
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data).toHaveProperty('content');
    expect(data.format).toBe('pptx');
  });

  test('export-hld 404 when HLD not generated', async ({ request }) => {
    const resp = await request.post(`${API_BASE}/api/diagrams/nonexistent-hld-export/export-hld?format=docx`);
    expect(resp.status()).toBe(404);
  });
});

