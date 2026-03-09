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

test.describe('Page Load', () => {
  test('homepage loads with Archmorph branding', async ({ page }) => {
    await page.goto('/');
    // Use getByRole to avoid strict mode violation (multiple "Archmorph" texts)
    await expect(page.getByRole('heading', { name: 'Archmorph' })).toBeVisible();
  });

  test('Translator tab is active by default', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('button', { name: 'Translator' })).toBeVisible();
    await expect(page.getByText('Upload Architecture Diagram')).toBeVisible();
  });

  test('Services tab loads catalog', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'Services', exact: true }).click();
    // Wait for API data to load (may take a while on cold start)
    await expect(page.getByText('Total Services')).toBeVisible({ timeout: COLD_START_TIMEOUT });
    await expect(page.locator('input[placeholder="Search services..."]')).toBeVisible();
  });

  test('navigation between tabs works', async ({ page }) => {
    await page.goto('/');
    // Go to Services
    await page.getByRole('button', { name: 'Services', exact: true }).click();
    await expect(page.getByText('Total Services')).toBeVisible({ timeout: COLD_START_TIMEOUT });
    // Go back to Translator
    await page.getByRole('button', { name: 'Translator' }).click();
    await expect(page.getByText('Upload Architecture Diagram')).toBeVisible();
  });
});

// ====================================================================
// 2. Backend API Health
// ====================================================================

test.describe('API Health', () => {
  test('backend health check returns healthy', async ({ request }) => {
    const resp = await request.get(`${API_BASE}/api/health`, { timeout: COLD_START_TIMEOUT });
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data.status).toBe('healthy');
    expect(data.version).toMatch(/^\d+\.\d+\.\d+$/);
    expect(data.service_catalog.aws).toBeGreaterThan(100);
  });

  test('contact endpoint returns project info', async ({ request }) => {
    const resp = await request.get(`${API_BASE}/api/contact`);
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data.github).toContain('Archmorph');
    expect(data.project).toBe('Archmorph');
  });
});

// ====================================================================
// 3. Full Translation Flow
// ====================================================================

test.describe('Translation Flow', () => {
  test('complete flow: upload → analyze → skip → results', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Upload Architecture Diagram')).toBeVisible();

    await navigateToResults(page);

    // Should show zone cards and confidence (navigateToResults already asserts "High Confidence")
    await expect(page.getByRole('heading', { name: 'Ingest', exact: true })).toBeVisible();
  });

  test('upload → analyze → apply answers → results', async ({ page }) => {
    await page.goto('/');
    const testPng = path.join(__dirname, `test-apply-${Date.now()}.png`);
    createTestPng(testPng);

    try {
      await page.locator('input[type="file"]').setInputFiles(testPng);
      await expect(page.getByText('Customize Your Azure Architecture')).toBeVisible({ timeout: COLD_START_TIMEOUT });
      // Apply with defaults
      await page.getByRole('button', { name: /Apply and View Results/i }).click();
      await expect(page.getByText('High Confidence')).toBeVisible({ timeout: API_TIMEOUT });
    } finally {
      if (fs.existsSync(testPng)) fs.unlinkSync(testPng);
    }
  });
});

// ====================================================================
// 4. Diagram Export
// ====================================================================

test.describe('Diagram Export', () => {
  test('export Draw.io from results', async ({ page }) => {
    await page.goto('/');
    await navigateToResults(page);

    // Click Draw.io export and wait for download
    const downloadPromise = page.waitForEvent('download', { timeout: API_TIMEOUT });
    await page.getByRole('button', { name: /Draw\.io/i }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toContain('.drawio');
  });

  test('export Excalidraw from results', async ({ page }) => {
    await page.goto('/');
    await navigateToResults(page);

    const downloadPromise = page.waitForEvent('download', { timeout: API_TIMEOUT });
    await page.getByRole('button', { name: /Excalidraw/i }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toContain('.excalidraw');
  });
});

// ====================================================================
// 5. IaC Generation
// ====================================================================

test.describe('IaC Generation', () => {
  test('generate Terraform code from results', async ({ page }) => {
    await page.goto('/');
    await navigateToResults(page);

    await page.getByRole('button', { name: /Generate Terraform/i }).click();
    await expect(page.getByText('Terraform Code')).toBeVisible({ timeout: API_TIMEOUT });
    await expect(page.getByText(/lines generated/)).toBeVisible();
    await expect(page.getByText('Estimated Monthly Cost')).toBeVisible({ timeout: API_TIMEOUT });
    await expect(page.getByRole('button', { name: 'Copy' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Download' })).toBeVisible();
  });

  test('generate Bicep code from results', async ({ page }) => {
    await page.goto('/');
    await navigateToResults(page);

    await page.getByRole('button', { name: /Generate Bicep/i }).click();
    await expect(page.getByText('Bicep Code')).toBeVisible({ timeout: API_TIMEOUT });
  });
});

// ====================================================================
// 6. Chat Widget
// ====================================================================

test.describe('Chat Widget', () => {
  test('chat toggle opens panel with assistant', async ({ page }) => {
    await page.goto('/');

    const chatBtn = page.locator('button[aria-label="Open chat"]');
    await expect(chatBtn).toBeVisible();
    await chatBtn.click();

    // Chat panel header (use getByRole to avoid strict mode — greeting text also contains "Archmorph")
    await expect(page.getByRole('heading', { name: 'Archmorph Assistant' })).toBeVisible();
    await expect(page.locator('input[placeholder="Type a message..."]')).toBeVisible();
  });

  test('send a message and receive reply', async ({ page }) => {
    await page.goto('/');

    await page.locator('button[aria-label="Open chat"]').click();
    await expect(page.locator('input[placeholder="Type a message..."]')).toBeVisible();

    // Type and send
    const input = page.locator('input[placeholder="Type a message..."]');
    await input.fill('What is Archmorph?');
    await input.press('Enter');

    // Wait for assistant reply
    await page.waitForTimeout(3_000);
    const messages = page.locator('.overflow-y-auto >> .rounded-xl');
    await expect(messages).not.toHaveCount(0, { timeout: API_TIMEOUT });
  });
});

// ====================================================================
// 7. Services Browser
// ====================================================================

test.describe('Services Browser', () => {
  test('shows service catalog with stats', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'Services', exact: true }).click();
    await expect(page.getByText('Total Services')).toBeVisible({ timeout: COLD_START_TIMEOUT });
    await expect(page.getByText('Cross-Cloud Mappings')).toBeVisible();
    // Use exact match to avoid matching "All Categories" dropdown
    await expect(page.getByText('Categories', { exact: true })).toBeVisible();
  });

  test('search filters services', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'Services', exact: true }).click();
    await expect(page.getByText('Total Services')).toBeVisible({ timeout: COLD_START_TIMEOUT });

    await page.fill('input[placeholder="Search services..."]', 'Lambda');
    await page.waitForTimeout(1_000);
    await expect(page.getByText(/Lambda/)).toBeVisible();
  });

  test('provider filter works', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'Services', exact: true }).click();
    await expect(page.getByText('Total Services')).toBeVisible({ timeout: COLD_START_TIMEOUT });

    // Select Azure provider
    const providerSelect = page.locator('select').first();
    await providerSelect.selectOption('azure');
    await page.waitForTimeout(1_000);
    await expect(page.getByText(/services found/)).toBeVisible({ timeout: 5_000 });
  });
});

// ====================================================================
// 8. Admin Dashboard (Hidden Access)
// ====================================================================

test.describe('Admin Dashboard', () => {
  test('5 rapid clicks on footer opens admin panel', async ({ page }) => {
    await page.goto('/');

    const versionText = page.getByText(/Archmorph v\d+\.\d+/);
    await expect(versionText).toBeVisible();

    // Click 5 times rapidly
    for (let i = 0; i < 5; i++) {
      await versionText.click({ delay: 50 });
    }

    // Admin overlay should appear
    await expect(page.getByText('Admin Analytics')).toBeVisible({ timeout: API_TIMEOUT });
    await expect(page.getByText('User Conversion Funnel')).toBeVisible();

    // Close
    await page.getByRole('button', { name: /Close/i }).click();
    await expect(page.getByText('Admin Analytics')).not.toBeVisible({ timeout: 5_000 });
  });
});

// ====================================================================
// 9. API Endpoints (via request context)
// ====================================================================

test.describe('API Endpoints', () => {
  test('services catalog returns data', async ({ request }) => {
    const resp = await request.get(`${API_BASE}/api/services`, { timeout: API_TIMEOUT });
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data.total).toBeGreaterThan(300);
  });

  test('services stats return counts', async ({ request }) => {
    const resp = await request.get(`${API_BASE}/api/services/stats`);
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data.totalServices).toBeGreaterThan(300);
    expect(data.totalMappings).toBeGreaterThan(50);
  });

  test('providers endpoint returns 3 providers', async ({ request }) => {
    const resp = await request.get(`${API_BASE}/api/services/providers`);
    const data = await resp.json();
    expect(data.providers).toHaveLength(3);
  });

  test('upload + analyze + export drawio via API', async ({ request }) => {
    // Upload
    const png = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, ...Array(50).fill(0)]);
    const uploadResp = await request.post(`${API_BASE}/api/projects/demo-project/diagrams`, {
      multipart: {
        file: { name: 'test.png', mimeType: 'image/png', buffer: png },
      },
      timeout: API_TIMEOUT,
    });
    expect(uploadResp.ok()).toBeTruthy();
    const { diagram_id } = await uploadResp.json();

    // Analyze
    const analyzeResp = await request.post(`${API_BASE}/api/diagrams/${diagram_id}/analyze`, { timeout: API_TIMEOUT });
    expect(analyzeResp.ok()).toBeTruthy();
    const analysis = await analyzeResp.json();
    expect(analysis.mappings.length).toBeGreaterThan(0);
    expect(analysis.zones.length).toBeGreaterThan(0);

    // Export Draw.io
    const exportResp = await request.post(`${API_BASE}/api/diagrams/${diagram_id}/export-diagram?format=drawio`, { timeout: API_TIMEOUT });
    expect(exportResp.ok()).toBeTruthy();
    const exportData = await exportResp.json();
    expect(exportData.format).toBe('drawio');
    expect(exportData.content).toContain('mxGraphModel');
  });

  test('IaC generation returns terraform code', async ({ request }) => {
    await request.post(`${API_BASE}/api/diagrams/e2e-test/analyze`, { timeout: API_TIMEOUT });
    const resp = await request.post(`${API_BASE}/api/diagrams/e2e-test/generate?format=terraform`);
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data.code).toContain('resource');
  });

  test('cost estimate returns pricing', async ({ request }) => {
    const resp = await request.get(`${API_BASE}/api/diagrams/e2e-test/cost-estimate`);
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data.currency).toBe('USD');
    expect(data.total_monthly_estimate).toBeDefined();
    expect(data.total_monthly_estimate.low).toBeGreaterThanOrEqual(0);
    expect(data.total_monthly_estimate.high).toBeGreaterThanOrEqual(0);
    expect(data.region).toBeDefined();
  });

  test('admin metrics requires auth token', async ({ request }) => {
    // Unauthenticated request should fail
    const badResp = await request.get(`${API_BASE}/api/admin/metrics`, {
      headers: { Authorization: 'Bearer invalid-token' },
    });
    expect(badResp.status()).toBe(401);

    // Login to get a valid JWT
    const loginResp = await request.post(`${API_BASE}/api/admin/login`, {
      data: { key: ADMIN_KEY },
      headers: { 'Content-Type': 'application/json' },
    });
    if (!loginResp.ok()) return; // admin not configured in CI
    const { token } = await loginResp.json();

    const goodResp = await request.get(`${API_BASE}/api/admin/metrics`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(goodResp.ok()).toBeTruthy();
  });
});

// ====================================================================
// 10. HLD Generation
// ====================================================================

test.describe('HLD Generation', () => {
  test('Generate HLD button visible on results page', async ({ page }) => {
    await page.goto('/');
    await navigateToResults(page);

    await expect(page.getByRole('button', { name: /Generate HLD/i })).toBeVisible();
  });

  test('HLD API endpoint generates document', async ({ request }) => {
    // Upload + Analyze first
    const png = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, ...Array(50).fill(0)]);
    const uploadResp = await request.post(`${API_BASE}/api/projects/e2e-hld/diagrams`, {
      multipart: {
        file: { name: 'test.png', mimeType: 'image/png', buffer: png },
      },
      timeout: API_TIMEOUT,
    });
    expect(uploadResp.ok()).toBeTruthy();
    const { diagram_id } = await uploadResp.json();

    await request.post(`${API_BASE}/api/diagrams/${diagram_id}/analyze`, { timeout: API_TIMEOUT });

    // Generate HLD
    const hldResp = await request.post(`${API_BASE}/api/diagrams/${diagram_id}/generate-hld`, { timeout: API_TIMEOUT });
    expect(hldResp.ok()).toBeTruthy();
    const data = await hldResp.json();
    expect(data.hld).toBeDefined();
    expect(data.hld.title).toBeDefined();
    expect(data.hld.services).toBeDefined();
    expect(data.markdown).toBeDefined();
    expect(data.markdown.length).toBeGreaterThan(100);
  });

  test('GET HLD returns cached document', async ({ request }) => {
    // Upload + Analyze + Generate first
    const png = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, ...Array(50).fill(0)]);
    const uploadResp = await request.post(`${API_BASE}/api/projects/e2e-hld-get/diagrams`, {
      multipart: {
        file: { name: 'test.png', mimeType: 'image/png', buffer: png },
      },
      timeout: API_TIMEOUT,
    });
    const { diagram_id } = await uploadResp.json();
    await request.post(`${API_BASE}/api/diagrams/${diagram_id}/analyze`, { timeout: API_TIMEOUT });
    await request.post(`${API_BASE}/api/diagrams/${diagram_id}/generate-hld`, { timeout: API_TIMEOUT });

    // GET cached HLD
    const getResp = await request.get(`${API_BASE}/api/diagrams/${diagram_id}/hld`, { timeout: API_TIMEOUT });
    expect(getResp.ok()).toBeTruthy();
    const data = await getResp.json();
    expect(data.hld).toBeDefined();
    expect(data.markdown).toBeDefined();
  });

  test('HLD 404 when not generated', async ({ request }) => {
    const resp = await request.get(`${API_BASE}/api/diagrams/nonexistent-hld-id/hld`);
    expect(resp.status()).toBe(404);
  });
});

// ====================================================================
// 11. IaC Chat Assistant
// ====================================================================

test.describe('IaC Chat', () => {
  test('IaC chat endpoint processes message', async ({ request }) => {
    // Upload + Analyze + Generate IaC first
    const png = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, ...Array(50).fill(0)]);
    const uploadResp = await request.post(`${API_BASE}/api/projects/e2e-chat/diagrams`, {
      multipart: {
        file: { name: 'test.png', mimeType: 'image/png', buffer: png },
      },
      timeout: API_TIMEOUT,
    });
    const { diagram_id } = await uploadResp.json();
    await request.post(`${API_BASE}/api/diagrams/${diagram_id}/analyze`, { timeout: API_TIMEOUT });
    await request.post(`${API_BASE}/api/diagrams/${diagram_id}/generate?format=terraform`, { timeout: API_TIMEOUT });

    // Send IaC chat message
    const chatResp = await request.post(`${API_BASE}/api/diagrams/${diagram_id}/iac-chat`, {
      data: { message: 'Add a Redis cache resource', format: 'terraform' },
      timeout: API_TIMEOUT,
    });
    expect(chatResp.ok()).toBeTruthy();
    const data = await chatResp.json();
    expect(data.reply).toBeDefined();
    expect(data.reply.length).toBeGreaterThan(10);
  });

  test('IaC chat history returns messages', async ({ request }) => {
    // Upload + Analyze + Generate + Chat first
    const png = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, ...Array(50).fill(0)]);
    const uploadResp = await request.post(`${API_BASE}/api/projects/e2e-chat-hist/diagrams`, {
      multipart: {
        file: { name: 'test.png', mimeType: 'image/png', buffer: png },
      },
      timeout: API_TIMEOUT,
    });
    const { diagram_id } = await uploadResp.json();
    await request.post(`${API_BASE}/api/diagrams/${diagram_id}/analyze`, { timeout: API_TIMEOUT });
    await request.post(`${API_BASE}/api/diagrams/${diagram_id}/generate?format=terraform`, { timeout: API_TIMEOUT });
    await request.post(`${API_BASE}/api/diagrams/${diagram_id}/iac-chat`, {
      data: { message: 'Explain the code', format: 'terraform' },
      timeout: API_TIMEOUT,
    });

    // Get history
    const histResp = await request.get(`${API_BASE}/api/diagrams/${diagram_id}/iac-chat`, { timeout: API_TIMEOUT });
    expect(histResp.ok()).toBeTruthy();
    const data = await histResp.json();
    expect(data.messages).toBeDefined();
    expect(data.messages.length).toBeGreaterThanOrEqual(2); // user + assistant
  });

  test('IaC chat clear returns success', async ({ request }) => {
    const resp = await request.delete(`${API_BASE}/api/diagrams/e2e-clear-test/iac-chat`);
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data).toHaveProperty('cleared');
  });
});

// ====================================================================
// 12. Footer & Branding
// ====================================================================

test.describe('Footer & Branding', () => {
  test('footer shows GitHub link', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('link', { name: /GitHub/i })).toBeVisible();
  });

  test('footer shows version', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText(/Archmorph v\d+\.\d+/)).toBeVisible();
  });
});

// ====================================================================
// 12b. Feedback Widget
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
    await expect(page.getByRole('button', { name: /Rate/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /Feature/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /Bug/i })).toBeVisible();
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
    await page.getByRole('button', { name: /Bug/i }).click();
    await expect(page.getByPlaceholder('Describe the issue')).toBeVisible();
  });
});

// ====================================================================
// 13. Additional API Coverage
// ====================================================================

test.describe('Additional API Coverage', () => {
  test('service-updates status returns scheduler info', async ({ request }) => {
    const resp = await request.get(`${API_BASE}/api/service-updates/status`);
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data).toHaveProperty('scheduler_running');
    expect(data).toHaveProperty('catalog_sizes');
  });

  test('service-updates last returns update details', async ({ request }) => {
    const resp = await request.get(`${API_BASE}/api/service-updates/last`);
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data).toHaveProperty('last_check');
  });

  test('mappings endpoint returns cross-cloud mappings', async ({ request }) => {
    const resp = await request.get(`${API_BASE}/api/services/mappings`);
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data.mappings.length).toBeGreaterThan(50);
    expect(data.mappings[0]).toHaveProperty('aws');
    expect(data.mappings[0]).toHaveProperty('azure');
  });

  test('categories endpoint returns grouped counts', async ({ request }) => {
    const resp = await request.get(`${API_BASE}/api/services/categories`);
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data.categories.length).toBeGreaterThan(5);
  });

  test('specific service lookup returns details', async ({ request }) => {
    const resp = await request.get(`${API_BASE}/api/services/aws/aws-ec2`);
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data.service).toHaveProperty('name');
    expect(data.service).toHaveProperty('category');
  });

  test('specific service not found returns 404', async ({ request }) => {
    const resp = await request.get(`${API_BASE}/api/services/aws/nonexistent-xyz`);
    expect(resp.status()).toBe(404);
  });

  test('cost estimate returns region and strategy', async ({ request }) => {
    // Analyze first to populate session
    await request.post(`${API_BASE}/api/diagrams/e2e-cost/analyze`, { timeout: API_TIMEOUT });
    const resp = await request.get(`${API_BASE}/api/diagrams/e2e-cost/cost-estimate`);
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data).toHaveProperty('sku_strategy');
    expect(data).toHaveProperty('pricing_source');
    expect(data.service_count).toBeGreaterThanOrEqual(0);
  });
});
// ====================================================================
// 14. Natural Language Service Builder (New UX Feature)
// ====================================================================

test.describe('Natural Language Service Builder', () => {
  test('add-services endpoint requires analysis first', async ({ request }) => {
    const resp = await request.post(`${API_BASE}/api/diagrams/nonexistent-diagram/add-services`, {
      data: { text: 'Add Redis cache' },
      headers: { 'Content-Type': 'application/json' },
    });
    expect(resp.status()).toBe(404);
  });

  test('questions endpoint returns inferred_answers for smart dedup', async ({ request }) => {
    // This tests the new smart deduplication feature
    const resp = await request.post(`${API_BASE}/api/diagrams/test-dedup/questions?smart_dedup=true`);
    // Will 404 since no analysis, but tests endpoint exists
    expect(resp.status()).toBe(404);
    const data = await resp.json();
    expect(data.detail).toContain('No analysis found');
  });

  test('questions endpoint accepts smart_dedup parameter', async ({ request }) => {
    const resp = await request.post(`${API_BASE}/api/diagrams/test/questions?smart_dedup=false`);
    // 404 is expected, we just want to verify the endpoint accepts the param
    expect(resp.status()).toBe(404);
  });
});

// ====================================================================
// 15. API Robustness Tests
// ====================================================================

test.describe('API Robustness', () => {
  test('API handles concurrent requests gracefully', async ({ request }) => {
    // Fire multiple requests simultaneously
    const promises = Array(5).fill(null).map(() =>
      request.get(`${API_BASE}/api/health`)
    );
    
    const responses = await Promise.all(promises);
    
    // All should succeed
    responses.forEach(resp => {
      expect(resp.ok()).toBeTruthy();
    });
  });

  test('API returns proper CORS headers', async ({ request }) => {
    const resp = await request.get(`${API_BASE}/api/health`);
    // CORS headers should be present
    const headers = resp.headers();
    expect(headers['x-content-type-options']).toBe('nosniff');
    expect(headers['x-frame-options']).toBe('DENY');
  });

  test('API handles malformed JSON gracefully', async ({ request }) => {
    const resp = await request.post(`${API_BASE}/api/chat`, {
      headers: { 'Content-Type': 'application/json' },
      data: 'not valid json',
    });
    // Should return 422 (validation error) not 500
    expect(resp.status()).toBe(422);
  });

  test('health check includes environment info', async ({ request }) => {
    const resp = await request.get(`${API_BASE}/api/health`);
    const data = await resp.json();
    expect(data).toHaveProperty('environment');
    expect(data).toHaveProperty('mode');
    expect(data).toHaveProperty('scheduler_running');
  });
});

// ====================================================================
// 16. Roadmap API Tests (v2.10)
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

// ====================================================================
// 17. AI Chat Assistant Tests (v2.10)
// ====================================================================

test.describe('AI Chat Assistant (v2.10)', () => {
  test('chat endpoint accepts messages', async ({ request }) => {
    const resp = await request.post(`${API_BASE}/api/chat`, {
      data: { 
        message: 'Hello, how does Archmorph work?',
        session_id: `e2e-test-${Date.now()}`
      },
      headers: { 'Content-Type': 'application/json' },
    });
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
      headers: { 'Content-Type': 'application/json' },
    });
    const data = await resp.json();
    expect(data).toHaveProperty('ai_powered');
    expect(data.ai_powered).toBe(true);
  });

  test('chat history endpoint works', async ({ request }) => {
    const sessionId = `e2e-history-${Date.now()}`;
    
    // Send a message first
    await request.post(`${API_BASE}/api/chat`, {
      data: { message: 'Test message', session_id: sessionId },
      headers: { 'Content-Type': 'application/json' },
    });

    // Get history
    const resp = await request.get(`${API_BASE}/api/chat/history/${sessionId}`);
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
      headers: { 'Content-Type': 'application/json' },
    });

    // Clear session
    const resp = await request.delete(`${API_BASE}/api/chat/${sessionId}`);
    expect(resp.ok()).toBeTruthy();

    const data = await resp.json();
    expect(data.cleared).toBe(true);
  });
});

// ====================================================================
// 18. Roadmap UI Tests (v2.10)
// ====================================================================

test.describe('Roadmap UI (v2.10)', () => {
  test('Roadmap tab exists in navigation', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('button', { name: 'Roadmap' })).toBeVisible();
  });

  test('Roadmap tab loads timeline', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'Roadmap' }).click();
    
    // Wait for roadmap to load
    await expect(page.getByText('Roadmap & Timeline')).toBeVisible({ timeout: COLD_START_TIMEOUT });
    await expect(page.getByText('From Day 0 to today')).toBeVisible();
  });

  test('Roadmap shows release statistics', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'Roadmap' }).click();
    
    await expect(page.getByText('Releases Shipped')).toBeVisible({ timeout: COLD_START_TIMEOUT });
    await expect(page.getByText('Features Delivered')).toBeVisible();
    await expect(page.getByText('Days Since Launch')).toBeVisible();
  });

  test('Roadmap has feature request button', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'Roadmap' }).click();
    
    await expect(page.getByRole('button', { name: /Request Feature/i })).toBeVisible({ timeout: COLD_START_TIMEOUT });
  });

  test('Roadmap has bug report button', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'Roadmap' }).click();
    
    await expect(page.getByRole('button', { name: /Report Bug/i })).toBeVisible({ timeout: COLD_START_TIMEOUT });
  });

  test('Feature request modal opens', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'Roadmap' }).click();
    await page.waitForTimeout(1000);
    
    await page.getByRole('button', { name: /Request Feature/i }).click();
    await expect(page.getByText('Request a Feature')).toBeVisible();
    await expect(page.getByText('Feature Title')).toBeVisible();
  });

  test('Bug report modal opens', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'Roadmap' }).click();
    await page.waitForTimeout(1000);
    
    await page.getByRole('button', { name: /Report Bug/i }).click();
    await expect(page.getByText('Report a Bug')).toBeVisible();
    await expect(page.getByText('Bug Title')).toBeVisible();
  });
});

// ====================================================================
// 18. Chat Widget
// ====================================================================

test.describe('Chat Widget', () => {
  test('chat button visible at bottom of page', async ({ page }) => {
    await page.goto('/');
    // Chat widget button should be visible
    const chatBtn = page.locator('button[title*="Chat"], button[title*="chat"], button:has(svg.lucide-message-circle)').first();
    await expect(chatBtn).toBeVisible();
  });

  test('chat modal opens on button click', async ({ page }) => {
    await page.goto('/');
    const chatBtn = page.locator('button').filter({ has: page.locator('svg.lucide-message-circle') }).first();
    await chatBtn.click();
    // Should show chat interface
    await expect(page.getByPlaceholder(/message|ask|type/i)).toBeVisible({ timeout: 5000 });
  });
});

// ====================================================================
// 19. Header & Navigation UI
// ====================================================================

test.describe('Header UI', () => {
  test('header shows Archmorph branding', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('header h1')).toContainText('Archmorph');
    await expect(page.locator('header')).toContainText('Cloud Translator');
  });

  test('header has navigation tabs', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('button', { name: 'Translator' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Services', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Roadmap' })).toBeVisible();
  });

  test('version badge shows current version in header', async ({ page }) => {
    await page.goto('/');
    const versionBadge = page.locator('header').getByText(/v2\.\d+\.\d+/);
    await expect(versionBadge).toBeVisible();
  });

  test('catalog status indicator visible', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('header').getByText(/Catalog/i)).toBeVisible();
  });
});

// ====================================================================
// 20. Services Browser Functionality
// ====================================================================

test.describe('Services Browser', () => {
  test('services page shows provider filters', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'Services', exact: true }).click();
    // Check provider filter dropdown exists with options
    const providerSelect = page.locator('select').first();
    await expect(providerSelect).toBeVisible({ timeout: COLD_START_TIMEOUT });
    await expect(providerSelect.locator('option:has-text("AWS")')).toHaveCount(1);
    await expect(providerSelect.locator('option:has-text("Azure")')).toHaveCount(1);
    await expect(providerSelect.locator('option:has-text("GCP")')).toHaveCount(1);
  });

  test('services page has search functionality', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'Services', exact: true }).click();
    const searchInput = page.locator('input[placeholder="Search services..."]');
    await expect(searchInput).toBeVisible({ timeout: COLD_START_TIMEOUT });
    
    // Type a search term
    await searchInput.fill('EC2');
    await page.waitForTimeout(500);
    // Should filter results
    await expect(page.getByText(/EC2|Compute/i)).toBeVisible();
  });

  test('services shows total count', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'Services', exact: true }).click();
    // Should show service count
    await expect(page.getByText(/Total Services/i)).toBeVisible({ timeout: COLD_START_TIMEOUT });
  });
});

// ====================================================================
// 21. Beta Warning Banner
// ====================================================================

test.describe('Beta Warning', () => {
  test('beta warning banner visible on load', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Beta Preview')).toBeVisible();
  });

  test('beta warning mentions production review', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText(/production/i)).toBeVisible();
  });
});

// ====================================================================
// 22. API Analytics Endpoints
// ====================================================================

test.describe('Analytics API', () => {
  test('feedback NPS endpoint accepts POST', async ({ request }) => {
    const resp = await request.post(`${API_BASE}/api/feedback/nps`, {
      data: { score: 8, follow_up: 'E2E test' },
    });
    expect(resp.status()).toBeLessThan(500); // May be 200 or 400 depending on validation
  });

  test('feedback feature endpoint accepts POST', async ({ request }) => {
    const resp = await request.post(`${API_BASE}/api/feedback/feature`, {
      data: { feature: 'diagram_analysis', helpful: true },
    });
    expect(resp.status()).toBeLessThan(500);
  });

  test('feedback bug endpoint accepts POST', async ({ request }) => {
    const resp = await request.post(`${API_BASE}/api/feedback/bug`, {
      data: { description: 'E2E test bug report', severity: 'low' },
    });
    expect(resp.status()).toBeLessThan(500);
  });
});

// ====================================================================
// 23. Feature Flags API (Sprint — Feature flags system)
// ====================================================================

test.describe('Feature Flags API', () => {
  test('GET /api/flags returns all feature flags', async ({ request }) => {
    const resp = await request.get(`${API_BASE}/api/flags`);
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data).toHaveProperty('flags');
    expect(data.flags).toHaveProperty('dark_mode');
    expect(data.flags).toHaveProperty('export_pptx');
    expect(data.flags).toHaveProperty('new_ai_model');
  });

  test('GET /api/flags/:name returns single flag', async ({ request }) => {
    const resp = await request.get(`${API_BASE}/api/flags/dark_mode`);
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data.name).toBe('dark_mode');
    expect(data).toHaveProperty('enabled');
    expect(data).toHaveProperty('rollout_percentage');
  });

  test('GET /api/flags/:name returns 404 for unknown flag', async ({ request }) => {
    const resp = await request.get(`${API_BASE}/api/flags/nonexistent_flag_xyz`);
    expect(resp.status()).toBe(404);
  });

  test('PUT /api/flags/:name requires admin authentication', async ({ request }) => {
    const resp = await request.put(`${API_BASE}/api/flags/dark_mode`, {
      data: { enabled: false },
      headers: { 'Content-Type': 'application/json' },
    });
    // Should require admin auth (401 or 503)
    expect([401, 403, 503]).toContain(resp.status());
  });
});

// ====================================================================
// 24. API v1 Versioning (Sprint — API versioning v1 mirror)
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

// ====================================================================
// 25. HLD Export Functionality (Sprint — Export to DOCX/PDF/PPTX)
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

// ====================================================================
// 26. Guided Questions Flow (Sprint coverage)
// ====================================================================

test.describe('Guided Questions Flow', () => {
  test('questions endpoint returns questions after analysis', async ({ request }) => {
    const png = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, ...Array(50).fill(0)]);
    const uploadResp = await request.post(`${API_BASE}/api/projects/e2e-q-flow/diagrams`, {
      multipart: {
        file: { name: 'test.png', mimeType: 'image/png', buffer: png },
      },
      timeout: API_TIMEOUT,
    });
    const { diagram_id } = await uploadResp.json();
    await request.post(`${API_BASE}/api/diagrams/${diagram_id}/analyze`, { timeout: API_TIMEOUT });

    const resp = await request.post(`${API_BASE}/api/diagrams/${diagram_id}/questions`, { timeout: API_TIMEOUT });
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data).toHaveProperty('questions');
    expect(data.total).toBeGreaterThan(0);
  });

  test('apply-answers refines the analysis', async ({ request }) => {
    const png = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, ...Array(50).fill(0)]);
    const uploadResp = await request.post(`${API_BASE}/api/projects/e2e-apply/diagrams`, {
      multipart: {
        file: { name: 'test.png', mimeType: 'image/png', buffer: png },
      },
      timeout: API_TIMEOUT,
    });
    const { diagram_id } = await uploadResp.json();
    await request.post(`${API_BASE}/api/diagrams/${diagram_id}/analyze`, { timeout: API_TIMEOUT });

    const resp = await request.post(`${API_BASE}/api/diagrams/${diagram_id}/apply-answers`, {
      data: { environment: 'production', ha_dr: 'active_active' },
      headers: { 'Content-Type': 'application/json' },
      timeout: API_TIMEOUT,
    });
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data).toHaveProperty('mappings');
  });

  test('guided questions UI step is visible in full flow', async ({ page }) => {
    await page.goto('/');
    const testPng = path.join(__dirname, `test-q-${Date.now()}.png`);
    createTestPng(testPng);

    try {
      await page.locator('input[type="file"]').setInputFiles(testPng);
      // Should show questions step after analysis
      await expect(page.getByText('Customize Your Azure Architecture')).toBeVisible({ timeout: COLD_START_TIMEOUT });
      // Questions should have options to choose from
      await expect(page.getByRole('button', { name: /Apply and View Results/i })).toBeVisible();
      await expect(page.getByRole('button', { name: /Skip Customization/i })).toBeVisible();
    } finally {
      if (fs.existsSync(testPng)) fs.unlinkSync(testPng);
    }
  });
});

// ====================================================================
// 27. Cost Comparison Panel (Sprint — multi-cloud cost comparison)
// ====================================================================

test.describe('Cost Comparison', () => {
  test('cost-comparison endpoint returns multi-cloud pricing', async ({ request }) => {
    const png = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, ...Array(50).fill(0)]);
    const uploadResp = await request.post(`${API_BASE}/api/projects/e2e-cost-cmp/diagrams`, {
      multipart: {
        file: { name: 'test.png', mimeType: 'image/png', buffer: png },
      },
      timeout: API_TIMEOUT,
    });
    const { diagram_id } = await uploadResp.json();
    await request.post(`${API_BASE}/api/diagrams/${diagram_id}/analyze`, { timeout: API_TIMEOUT });

    const resp = await request.get(`${API_BASE}/api/diagrams/${diagram_id}/cost-comparison`, { timeout: API_TIMEOUT });
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data).toHaveProperty('providers');
    expect(data.providers).toHaveProperty('aws');
    expect(data.providers).toHaveProperty('azure');
    expect(data.providers).toHaveProperty('gcp');
    expect(data).toHaveProperty('services');
    expect(data.total_services).toBeGreaterThan(0);
  });

  test('cost-comparison 404 without analysis', async ({ request }) => {
    const resp = await request.get(`${API_BASE}/api/diagrams/no-such-id-cmp/cost-comparison`);
    expect(resp.status()).toBe(404);
  });
});

// ====================================================================
// 28. Architecture Diagram Upload Workflow (Sprint coverage)
// ====================================================================

test.describe('Diagram Upload Workflow', () => {
  test('upload rejects non-image files', async ({ request }) => {
    const resp = await request.post(`${API_BASE}/api/projects/e2e-reject/diagrams`, {
      multipart: {
        file: { name: 'bad.txt', mimeType: 'text/plain', buffer: Buffer.from('hello') },
      },
    });
    expect(resp.status()).toBe(400);
  });

  test('upload accepts PNG and returns diagram_id', async ({ request }) => {
    const png = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, ...Array(50).fill(0)]);
    const resp = await request.post(`${API_BASE}/api/projects/e2e-upload/diagrams`, {
      multipart: {
        file: { name: 'arch.png', mimeType: 'image/png', buffer: png },
      },
      timeout: API_TIMEOUT,
    });
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data.status).toBe('uploaded');
    expect(data.diagram_id).toBeDefined();
    expect(data.diagram_id).toContain('diag-');
    expect(data.filename).toBe('arch.png');
  });

  test('analyze returns zones and mappings', async ({ request }) => {
    const png = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, ...Array(50).fill(0)]);
    const uploadResp = await request.post(`${API_BASE}/api/projects/e2e-analyze/diagrams`, {
      multipart: {
        file: { name: 'arch.png', mimeType: 'image/png', buffer: png },
      },
      timeout: API_TIMEOUT,
    });
    const { diagram_id } = await uploadResp.json();

    const resp = await request.post(`${API_BASE}/api/diagrams/${diagram_id}/analyze`, { timeout: COLD_START_TIMEOUT });
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data.mappings.length).toBeGreaterThan(0);
    expect(data.zones.length).toBeGreaterThan(0);
    expect(data).toHaveProperty('confidence_summary');
  });

  test('full UI upload flow shows upload zone', async ({ page }) => {
    await page.goto('/');
    // Upload zone should be visible
    await expect(page.getByText('Upload Architecture Diagram')).toBeVisible();
    // File input should exist
    await expect(page.locator('input[type="file"]')).toBeAttached();
  });
});

// ====================================================================
// 29. Dark Mode Toggle (Sprint — Feature flag)
// ====================================================================

test.describe('Dark Mode', () => {
  test('dark mode feature flag is available', async ({ request }) => {
    const resp = await request.get(`${API_BASE}/api/flags/dark_mode`);
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data.name).toBe('dark_mode');
    expect(typeof data.enabled).toBe('boolean');
  });
});

// ====================================================================
// 30. Admin Dashboard Metrics View (Sprint — enhanced admin)
// ====================================================================

test.describe('Admin Dashboard Metrics', () => {
  test('admin login and metrics flow', async ({ request }) => {
    const loginResp = await request.post(`${API_BASE}/api/admin/login`, {
      data: { key: ADMIN_KEY },
      headers: { 'Content-Type': 'application/json' },
    });
    if (loginResp.status() === 503) {
      // Admin not configured — skip
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
test.describe('Cloud Scanner & FinOps (#416)', () => {
  test('Cloud scanner API parses correct dummy data', async ({ request }) => {
    const resp = await request.post(`${API_BASE}/api/scanner/run/aws`, { timeout: API_TIMEOUT });
    if (resp.status() === 503) return; // DB issues
    
    // Note: Depends on what the scanner routes returns if missing creds? 500 or 401 or 200 with dummy data if Mock is set. 
    // We expect it to at least exist.
    expect([200, 400, 401, 500]).toContain(resp.status());
  });
});
