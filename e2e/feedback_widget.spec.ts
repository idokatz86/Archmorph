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

test.describe('Feedback Widget', () => {
  test('feedback button visible in header next to version', async ({ page }) => {
    await page.goto('/');
    // Feedback button should be in header (within first 100px from top)
    const feedbackBtn = page.locator('header button[title="Give Feedback"]');
    await expect(feedbackBtn).toBeVisible();
  });

  test('feedback modal opens on button click', async ({ page }) => {
    await page.goto('/');
    const feedbackBtn = page.locator('header button[title="Give Feedback"]');
    await feedbackBtn.click();
    // Modal should appear with feedback heading
    await expect(page.getByRole('heading', { name: 'Feedback' })).toBeVisible();
  });

  test('feedback modal has NPS rating scale', async ({ page }) => {
    await page.goto('/');
    await page.locator('header button[title="Give Feedback"]').click();
    // Should show 0-10 NPS scale
    await expect(page.getByText('How likely are you to recommend')).toBeVisible();
    // Check for rating buttons (0-10)
    await expect(page.getByRole('button', { name: '0' })).toBeVisible();
    await expect(page.getByRole('button', { name: '10' })).toBeVisible();
  });

  test('feedback modal has mode tabs (Rate, Feature, Bug)', async ({ page }) => {
    await page.goto('/');
    await page.locator('header button[title="Give Feedback"]').click();
    await expect(page.getByRole('button', { name: '⭐ Rate' })).toBeVisible();
    await expect(page.getByRole('button', { name: '💡 Feature' })).toBeVisible();
    await expect(page.getByRole('button', { name: '🐛 Bug' })).toBeVisible();
  });

  test('feedback modal closes on X click', async ({ page }) => {
    await page.goto('/');
    await page.locator('header button[title="Give Feedback"]').click();
    await expect(page.getByRole('heading', { name: 'Feedback' })).toBeVisible();
    // Close the modal
    await page.locator('button').filter({ has: page.locator('svg.lucide-x') }).click();
    // Modal should be hidden
    await expect(page.getByRole('heading', { name: 'Feedback' })).not.toBeVisible();
  });

  test('feedback can submit NPS score', async ({ page }) => {
    await page.goto('/');
    await page.locator('header button[title="Give Feedback"]').click();
    // Select score 9
    await page.getByRole('button', { name: '9' }).click();
    // Submit
    await page.getByRole('button', { name: 'Submit' }).click();
    // Should show thank you message
    await expect(page.getByText('Thank you!')).toBeVisible({ timeout: 10000 });
  });

  test('feedback Bug tab shows description field', async ({ page }) => {
    await page.goto('/');
    await page.locator('header button[title="Give Feedback"]').click();
    await page.getByRole('button', { name: '🐛 Bug' }).click();
    await expect(page.getByPlaceholder('Describe the issue')).toBeVisible();
  });
});

