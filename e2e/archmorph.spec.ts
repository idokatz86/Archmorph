/**
 * Archmorph E2E Tests — Playwright
 *
 * Tests the live deployed application end-to-end:
 *   Frontend: https://agreeable-ground-01012c003.2.azurestaticapps.net
 *   Backend:  https://archmorph-api.icyisland-c0dee6ba.northeurope.azurecontainerapps.io
 */

import { test, expect, Page } from '@playwright/test';
import path from 'path';
import fs from 'fs';

const API_BASE = 'https://archmorph-api.icyisland-c0dee6ba.northeurope.azurecontainerapps.io';

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
    await page.getByRole('button', { name: 'Services' }).click();
    // Wait for API data to load (may take a while on cold start)
    await expect(page.getByText('Total Services')).toBeVisible({ timeout: COLD_START_TIMEOUT });
    await expect(page.locator('input[placeholder="Search services..."]')).toBeVisible();
  });

  test('navigation between tabs works', async ({ page }) => {
    await page.goto('/');
    // Go to Services
    await page.getByRole('button', { name: 'Services' }).click();
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
    expect(data.version).toBe('2.1.0');
    expect(data.service_catalog.aws).toBeGreaterThan(100);
  });

  test('contact endpoint returns email', async ({ request }) => {
    const resp = await request.get(`${API_BASE}/api/contact`);
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data.email).toBe('send2katz@gmail.com');
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
    await page.getByRole('button', { name: 'Services' }).click();
    await expect(page.getByText('Total Services')).toBeVisible({ timeout: COLD_START_TIMEOUT });
    await expect(page.getByText('Cross-Cloud Mappings')).toBeVisible();
    // Use exact match to avoid matching "All Categories" dropdown
    await expect(page.getByText('Categories', { exact: true })).toBeVisible();
  });

  test('search filters services', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'Services' }).click();
    await expect(page.getByText('Total Services')).toBeVisible({ timeout: COLD_START_TIMEOUT });

    await page.fill('input[placeholder="Search services..."]', 'Lambda');
    await page.waitForTimeout(1_000);
    await expect(page.getByText(/Lambda/)).toBeVisible();
  });

  test('provider filter works', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'Services' }).click();
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

    const versionText = page.getByText('Archmorph v2.1.0', { exact: false });
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

  test('admin metrics requires auth key', async ({ request }) => {
    const badResp = await request.get(`${API_BASE}/api/admin/metrics?key=wrong`);
    expect(badResp.status()).toBe(403);

    const goodResp = await request.get(`${API_BASE}/api/admin/metrics?key=archmorph-admin-2025`);
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
  test('footer shows contact email', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('send2katz@gmail.com')).toBeVisible();
  });

  test('footer shows version', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Archmorph v2.1.0')).toBeVisible();
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
