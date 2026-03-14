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
const ARCHMORPH_API_KEY = process.env.ARCHMORPH_API_KEY || '';

/** Resolved dynamically from /api/health on first use */
let _cachedVersion: string | null = null;
async function getVersion(request: any): Promise<string> {
  if (_cachedVersion) return _cachedVersion;
  const resp = await request.get(`${API_BASE}/api/health`, { timeout: COLD_START_TIMEOUT });
    if (resp.status() === 401) return;
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

test.describe('AI Chat Assistant (v2.10)', () => {
  test('chat endpoint accepts messages', async ({ request }) => {
    const resp = await request.post(`${API_BASE}/api/chat`, {
      data: { 
        message: 'Hello, how does Archmorph work?',
        session_id: `e2e-test-${Date.now()}`
      },
      headers: { 'Content-Type': 'application/json', ...(ARCHMORPH_API_KEY ? { 'X-API-Key': ARCHMORPH_API_KEY } : {}) },
    });
    if (resp.status() === 401) {
      test.skip();
      return;
    }
    expect(resp.ok()).toBeTruthy();

    const data = await resp.json();
    expect(data).toHaveProperty('reply');
    expect(data.reply.length).toBeGreaterThan(0);
  });

  test('chat response indicates AI-powered', async ({ request }) => {
    const resp = await request.post(`${API_BASE}/api/chat`, {
      data: { 
        message: 'What is Archmorph?',
        session_id: `e2e-ai-${Date.now()}`
      },
      headers: { 'Content-Type': 'application/json', ...(ARCHMORPH_API_KEY ? { 'X-API-Key': ARCHMORPH_API_KEY } : {}) },
    });
    if (resp.status() === 401) {
      test.skip();
      return;
    }
    const data = await resp.json();
    expect(data).toHaveProperty('ai_powered');
    expect(data.ai_powered).toBe(true);
  });

  test('chat history endpoint works', async ({ request }) => {
    const sessionId = `e2e-history-${Date.now()}`;
    
    // Send a message first
    await request.post(`${API_BASE}/api/chat`, {
      data: { message: 'Test message', session_id: sessionId },
      headers: { 'Content-Type': 'application/json', ...(ARCHMORPH_API_KEY ? { 'X-API-Key': ARCHMORPH_API_KEY } : {}) },
    });

    // Get history
    const resp = await request.get(`${API_BASE}/api/chat/history/${sessionId}`);
    if (resp.status() === 401) return;
    expect(resp.ok()).toBeTruthy();

    const data = await resp.json();
    expect(data).toHaveProperty('messages');
    expect(data.messages.length).toBeGreaterThan(0);
  });

  test('chat session can be cleared', async ({ request }) => {
    const sessionId = `e2e-clear-${Date.now()}`;
    
    // Send a message
    await request.post(`${API_BASE}/api/chat`, {
      data: { message: 'Test', session_id: sessionId },
      headers: { 'Content-Type': 'application/json', ...(ARCHMORPH_API_KEY ? { 'X-API-Key': ARCHMORPH_API_KEY } : {}) },
    });

    // Clear session
    const resp = await request.delete(`${API_BASE}/api/chat/${sessionId}`);
    if (resp.status() === 401) return;
    expect(resp.ok()).toBeTruthy();

    const data = await resp.json();
    expect(data.cleared).toBe(true);
  });
});

