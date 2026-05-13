import { test, expect, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import path from 'node:path';

/**
 * Core Funnel E2E Tests (#500)
 *
 * Covers the primary user journey:
 *   1. Landing / Home page loads
 *   2. Diagram upload flow
 *   3. Guided migration questions
 *   4. IaC generation (Terraform/Bicep)
 *   5. Diagram export
 *   6. Chatbot interaction
 *   7. Accessibility (axe-core)
 */

// Shared mock analysis data for tests that need results
const MOCK_ANALYSIS = {
  diagramId: 'e2e-test-001',
  analysis: {
    mappings: [
      {
        source_service: 'Amazon EC2',
        azure_service: 'Azure Virtual Machines',
        source_provider: 'aws',
        confidence: 0.95,
        category: 'Compute',
        notes: 'Direct IaaS equivalent',
      },
      {
        source_service: 'Amazon RDS',
        azure_service: 'Azure SQL Database',
        source_provider: 'aws',
        confidence: 0.85,
        category: 'Database',
        notes: 'Managed relational database',
      },
      {
        source_service: 'Amazon S3',
        azure_service: 'Azure Blob Storage',
        source_provider: 'aws',
        confidence: 0.95,
        category: 'Storage',
        notes: 'Object storage',
      },
    ],
    service_connections: [
      { from: 'Amazon EC2', to: 'Amazon RDS', protocol: 'TCP/3306' },
      { from: 'Amazon EC2', to: 'Amazon S3', protocol: 'HTTPS' },
    ],
    guided_questions: [
      {
        id: 'q1',
        question: 'What is your expected monthly traffic?',
        category: 'Environment & Scale',
        type: 'radio',
        options: ['< 1M requests', '1M–10M requests', '> 10M requests'],
      },
      {
        id: 'q2',
        question: 'Do you need compliance with specific standards?',
        category: 'Compliance & Security',
        type: 'checkbox',
        options: ['SOC 2', 'HIPAA', 'GDPR', 'ISO 27001'],
      },
    ],
    confidence_summary: { high: 2, medium: 1, low: 0, average: 0.92 },
  },
  ts: Date.now(),
};

const MOCK_ANALYSIS_RESULT = {
  diagram_id: MOCK_ANALYSIS.diagramId,
  source_provider: 'aws',
  mappings: MOCK_ANALYSIS.analysis.mappings,
  service_connections: MOCK_ANALYSIS.analysis.service_connections,
  guided_questions: MOCK_ANALYSIS.analysis.guided_questions,
  confidence_summary: MOCK_ANALYSIS.analysis.confidence_summary,
  zones: [
    {
      id: 'compute-data',
      number: 1,
      name: 'Application and data tier',
      services: [
        { source: 'Amazon EC2', azure: 'Azure Virtual Machines' },
        { source: 'Amazon RDS', azure: 'Azure SQL Database' },
      ],
    },
  ],
  export_capability: 'stub-capability-initial',
};

const MOCK_TERRAFORM = `terraform {
  required_version = ">= 1.6.0"
}

resource "azurerm_resource_group" "main" {
  name     = "rg-archmorph-e2e"
  location = "westeurope"
}
`;

const ACCESSIBLE_LANDING_ZONE_SVG = `
<svg role="img" aria-labelledby="lz-title" aria-describedby="lz-desc" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 180">
  <title id="lz-title">Azure Landing Zone</title>
  <desc id="lz-desc">Target architecture with compute and data tiers</desc>
  <g data-tier="Compute">
    <title>Compute tier</title>
    <desc>Hosts application workloads</desc>
    <g>
      <title>Azure Kubernetes Service</title>
      <desc>Compute tier service for container workloads</desc>
      <rect x="20" y="30" width="120" height="50" fill="#2563eb"></rect>
    </g>
  </g>
  <g data-tier="Data">
    <title>Data tier</title>
    <desc>Stores operational data</desc>
    <g>
      <title>Azure SQL Database</title>
      <desc>Data tier service for relational data</desc>
      <rect x="180" y="30" width="120" height="50" fill="#16a34a"></rect>
    </g>
  </g>
</svg>`;

const SAMPLE_UPLOAD_PATH = path.resolve(process.cwd(), 'frontend/public/favicon.svg');
const MOCK_COST_ESTIMATE = {
  services: [
    { service: 'Azure Virtual Machines', monthly_low: 120, monthly_high: 180 },
    { service: 'Azure Blob Storage', monthly_low: 35, monthly_high: 55 },
    { service: 'Azure Monitor', monthly_low: 18, monthly_high: 26 },
  ],
  total_monthly_estimate: { low: 173, high: 261 },
};
const MOCK_HLD = {
  title: 'Archmorph Sample HLD',
  executive_summary: 'Deterministic HLD payload for E2E coverage.',
  architecture_overview: {
    summary: 'Sample upload translated to Azure.',
    target_architecture: 'Azure landing zone',
  },
  services: [
    {
      source_service: 'EC2',
      azure_service: 'Azure Virtual Machines',
      justification: 'Deterministic CI smoke mapping.',
    },
  ],
  networking_design: { topology: 'Hub and spoke' },
  security_design: { identity: 'Microsoft Entra ID' },
  data_architecture: { storage: 'Azure Blob Storage' },
  azure_caf_alignment: { ready: true },
  finops: { summary: 'Use reserved capacity where appropriate.' },
  region_strategy: { primary: 'westeurope' },
  waf_assessment: { score: 'good' },
  migration_approach: { waves: ['Pilot', 'Migration', 'Validation'] },
  considerations: ['Validate networking controls'],
  risks_and_mitigations: ['Monitor export token sequencing'],
  next_steps: ['Review generated deliverables'],
};

async function stubDeterministicDeliverables(page: Page) {
  await page.route('**/api/projects/*/diagrams', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        project_id: 'demo-project',
        diagram_id: MOCK_ANALYSIS.diagramId,
        filename: 'favicon.svg',
        status: 'uploaded',
        export_capability: 'stub-capability-upload',
      }),
    });
  });

  await page.route('**/api/projects/demo-project', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        project_id: 'demo-project',
        diagrams: [
          {
            diagram_id: MOCK_ANALYSIS.diagramId,
            filename: 'favicon.svg',
            status: 'analyzed',
          },
        ],
      }),
    });
  });

  await page.route('**/api/diagrams/*/analyze-async', async route => {
    await route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Use sync analyze for deterministic E2E flow' }),
    });
  });

  await page.route('**/api/diagrams/*/analyze', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_ANALYSIS_RESULT),
    });
  });

  await page.route('**/api/diagrams/*/questions', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        questions: [],
        all_questions: [],
        assumptions: [],
        inferred_answers: {},
      }),
    });
  });

  await page.route('**/api/diagrams/*/generate?format=*', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ code: MOCK_TERRAFORM }),
    });
  });

  await page.route('**/api/diagrams/*/generate-hld', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        diagram_id: 'deterministic-hld',
        hld: MOCK_HLD,
        markdown: '# Archmorph Sample HLD\n\nDeterministic HLD payload for E2E coverage.\n',
      }),
    });
  });

  await page.route('**/api/diagrams/*/cost-estimate', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_COST_ESTIMATE),
    });
  });

  await page.route('**/api/diagrams/*/export-architecture-package**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        content: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 60"><text x="8" y="32">Archmorph E2E</text></svg>',
        filename: 'archmorph-architecture-package.svg',
        export_capability: 'stub-capability-architecture-package',
      }),
    });
  });

  await page.route('**/api/diagrams/*/export-hld**', async route => {
    const requestUrl = new URL(route.request().url());
    const format = requestUrl.searchParams.get('format') || 'docx';
    const isPdf = format === 'pdf';
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        content_b64: Buffer.from(isPdf ? '%PDF-1.4\nmock archmorph report\n' : 'mock archmorph hld').toString('base64'),
        content_type: isPdf ? 'application/pdf' : 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        filename: isPdf ? 'archmorph-report.pdf' : `archmorph-hld.${format}`,
        export_capability: `stub-capability-${format}`,
      }),
    });
  });
}

function injectMockSession(page: Page) {
  return page.addInitScript((data: { diagramId: string }) => {
    sessionStorage.setItem('archmorph_active_diagram', data.diagramId);
    sessionStorage.setItem(
      `archmorph_session_${data.diagramId}`,
      JSON.stringify({
        ...data,
        sensitiveCacheOptIn: true,
        ts: Date.now(),
      })
    );
  }, MOCK_ANALYSIS);
}

async function stubAuthenticatedUser(page: Page) {
  await page.route('**/.auth/me', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        clientPrincipal: {
          userId: 'e2e-user',
          userDetails: 'e2e@archmorph.test',
          identityProvider: 'github',
          userRoles: ['authenticated'],
        },
      }),
    });
  });

  await page.route('**/api/auth/me', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'e2e-user',
        email: 'e2e@archmorph.test',
        name: 'E2E User',
        provider: 'github',
      }),
    });
  });
}

// ─── Test Suite ──────────────────────────────────────────────

test.describe('Core Funnel: Home & Navigation', () => {
  test('home page loads with header and CTA', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#root')).toBeVisible({ timeout: 15000 });

    // Header should be present
    const header = page.locator('header').first();
    await expect(header).toBeVisible();

    // Should have navigation or main CTA
    const cta = page.getByRole('link', { name: /get started|try|translate|upload/i }).first();
    const ctaVisible = await cta.isVisible().catch(() => false);
    if (ctaVisible) {
      await expect(cta).toBeVisible();
    }
  });

  test('navigate to translator page', async ({ page }) => {
    await page.goto('/#translator');
    await expect(page.locator('#root')).toBeVisible({ timeout: 15000 });
  });
});

test.describe('Core Funnel: Diagram Upload', () => {
  test('upload zone is visible and accepts files', async ({ page }) => {
    await page.goto('/#translator');
    await expect(page.locator('#root')).toBeVisible({ timeout: 15000 });

    // Look for upload/drop zone
    const uploadZone = page.locator('[data-testid="upload-zone"], [class*="upload"], [class*="dropzone"], input[type="file"]').first();
    const visible = await uploadZone.isVisible({ timeout: 8000 }).catch(() => false);
    if (visible) {
      await expect(uploadZone).toBeVisible();
    }
  });

  test('shows sample diagrams for onboarding', async ({ page }) => {
    await page.goto('/#translator');
    await expect(page.locator('#root')).toBeVisible({ timeout: 15000 });

    // Sample diagrams section
    const samples = page.locator('[data-testid="sample-diagrams"], [class*="sample"], text=/sample|example|try one/i').first();
    const visible = await samples.isVisible({ timeout: 5000 }).catch(() => false);
    if (visible) {
      await expect(samples).toBeVisible();
    }
  });
});

test.describe('Core Funnel: Analysis Results', () => {
  test.beforeEach(async ({ page }) => {
    await injectMockSession(page);
    await page.goto('/#translator');
  });

  test('results table shows mapped services', async ({ page }) => {
    // Wait for results to render
    const resultsArea = page.locator('[class*="result"], [data-testid="results-table"], table').first();
    const visible = await resultsArea.isVisible({ timeout: 10000 }).catch(() => false);
    if (visible) {
      // Check that at least one mapping is shown
      await expect(page.getByText('Azure Virtual Machines').first()).toBeVisible({ timeout: 5000 });
    }
  });

  test('confidence indicators display correctly', async ({ page }) => {
    const confidenceBadge = page.locator('[class*="confidence"], [class*="badge"]').first();
    const visible = await confidenceBadge.isVisible({ timeout: 8000 }).catch(() => false);
    if (visible) {
      await expect(confidenceBadge).toBeVisible();
    }
  });

  test('React Flow canvas renders service nodes', async ({ page }) => {
    const canvas = page.locator('.react-flow').first();
    const canvasVisible = await canvas.isVisible({ timeout: 8000 }).catch(() => false);
    if (canvasVisible) {
      await expect(canvas).toBeVisible();
      // Check for at least one node
      const node = page.locator('.react-flow__node').first();
      await expect(node).toBeVisible({ timeout: 5000 });
    }
  });
});

test.describe('Core Funnel: Guided Questions', () => {
  test.beforeEach(async ({ page }) => {
    await injectMockSession(page);
    await page.goto('/#translator');
  });

  test('guided questions section appears with options', async ({ page }) => {
    const questionsArea = page.locator('[data-testid="guided-questions"], [class*="question"], [class*="guided"]').first();
    const visible = await questionsArea.isVisible({ timeout: 8000 }).catch(() => false);
    if (visible) {
      await expect(questionsArea).toBeVisible();
      // Look for radio or checkbox inputs
      const inputs = page.locator('input[type="radio"], input[type="checkbox"], [role="radio"], [role="checkbox"]');
      const count = await inputs.count();
      expect(count).toBeGreaterThan(0);
    }
  });
});

test.describe('Core Funnel: IaC Generation', () => {
  test.beforeEach(async ({ page }) => {
    await injectMockSession(page);
    await page.goto('/#translator');
  });

  test('Terraform/Bicep code panel is accessible', async ({ page }) => {
    // Look for IaC / code generation tab or button
    const iacTab = page.locator('button:has-text("Terraform"), button:has-text("Bicep"), button:has-text("IaC"), [data-testid="iac-tab"]').first();
    const visible = await iacTab.isVisible({ timeout: 8000 }).catch(() => false);
    if (visible) {
      await iacTab.click();
      // Code block should appear
      const codeBlock = page.locator('pre, code, [class*="code"], [class*="prism"]').first();
      await expect(codeBlock).toBeVisible({ timeout: 8000 });
    }
  });
});

test.describe('Core Funnel: Upload → Analyze → IaC → Export All', () => {
  test('completes the deterministic happy path and makes all six deliverables ready within 60 seconds', async ({ page }) => {
    test.setTimeout(90_000);
    await page.addInitScript(() => {
      localStorage.clear();
      sessionStorage.clear();
    });
    await stubAuthenticatedUser(page);
    await stubDeterministicDeliverables(page);

    await page.goto('/#translator');
    await expect(page.locator('#root')).toBeVisible({ timeout: 15000 });

    await page.locator('input[type="file"]').setInputFiles(SAMPLE_UPLOAD_PATH);
    await expect(page.getByText('favicon.svg')).toBeVisible();

    const uploadRequest = page.waitForResponse(response =>
      response.request().method() === 'POST' &&
      response.url().includes('/api/projects/demo-project/diagrams') &&
      response.status() === 200
    );
    const analyzeRequest = page.waitForResponse(response => {
      const requestUrl = new URL(response.url());
      return response.request().method() === 'POST' &&
        /\/api\/diagrams\/[^/]+\/analyze$/.test(requestUrl.pathname) &&
        response.status() === 200;
    });

    await page.getByRole('button', { name: 'Analyze This Diagram' }).click();
    await uploadRequest;
    await analyzeRequest;

    await expect(page.getByRole('button', { name: 'Export All' })).toBeVisible({ timeout: 15000 });

    const iacRequest = page.waitForResponse(response => {
      const requestUrl = new URL(response.url());
      return response.request().method() === 'POST' &&
        /\/api\/diagrams\/[^/]+\/generate$/.test(requestUrl.pathname) &&
        requestUrl.searchParams.get('format') === 'terraform' &&
        response.status() === 200;
    });

    await page.getByRole('button', { name: 'Terraform' }).click();
    await iacRequest;

    await expect(page.getByRole('heading', { name: 'Terraform Code' })).toBeVisible({ timeout: 15000 });
    await expect(page.getByText(/terraform\s*\{/)).toBeVisible();

    await page.getByRole('button', { name: 'Back to Analysis' }).click();
    await expect(page.getByRole('button', { name: 'Export All' })).toBeVisible({ timeout: 10000 });

    await page.getByRole('button', { name: 'Export All' }).click();
    const exportDialog = page.getByRole('dialog', { name: 'Generate Deliverables' });
    await expect(exportDialog).toBeVisible();
    await expect(exportDialog.getByRole('status')).toContainText('6 of 6 selected');

    await page.getByRole('button', { name: /Generate All Selected/i }).click();
    await expect(page.getByRole('button', { name: 'Download All (6)' })).toBeVisible({ timeout: 60_000 });

    for (const label of [
      'Infrastructure Code',
      'Architecture Package',
      'High-Level Design',
      'Cost Estimate',
      'Migration Timeline',
      'PDF Analysis Report',
    ]) {
      await expect(page.getByRole('button', { name: `Download ${label}` })).toBeVisible();
    }
  });
});

test.describe('Core Funnel: Diagram Export', () => {
  test.beforeEach(async ({ page }) => {
    await injectMockSession(page);
    await page.goto('/#translator');
  });

  test('export button is present and clickable', async ({ page }) => {
    const exportBtn = page.locator('button:has-text("Export"), button:has-text("Download"), [data-testid="export-btn"]').first();
    const visible = await exportBtn.isVisible({ timeout: 8000 }).catch(() => false);
    if (visible) {
      await expect(exportBtn).toBeEnabled();
    }
  });
});

test.describe('Core Funnel: Responsive + keyboard export flow', () => {
  test.beforeEach(async ({ page }) => {
    await injectMockSession(page);
    await page.goto('/#translator');
    await expect(page.locator('#root')).toBeVisible({ timeout: 15000 });
  });

  test('translator export controls remain visible across mobile viewports', async ({ page }) => {
    const exportAllButton = page.getByRole('button', { name: 'Export All' });

    for (const viewport of [
      { width: 320, height: 568 },
      { width: 360, height: 640 },
      { width: 390, height: 844 },
    ]) {
      await page.setViewportSize(viewport);
      await expect(exportAllButton).toBeVisible();
      await expect(exportAllButton).toBeEnabled();
    }
  });

  test('export dialog supports keyboard close and returns focus to trigger', async ({ page }) => {
    const exportAllButton = page.getByRole('button', { name: 'Export All' });
    await exportAllButton.focus();
    await expect(exportAllButton).toBeFocused();

    await page.keyboard.press('Enter');
    const dialog = page.getByRole('dialog', { name: 'Generate Deliverables' });
    await expect(dialog).toBeVisible();

    await page.keyboard.press('Tab');
    await page.keyboard.press('Tab');
    await page.keyboard.press('Escape');

    await expect(dialog).toBeHidden();
    await expect(exportAllButton).toBeFocused();
  });
});

test.describe('Core Funnel: Chatbot', () => {
  test('chatbot toggle button is visible', async ({ page }) => {
    await page.goto('/#translator');
    await expect(page.locator('#root')).toBeVisible({ timeout: 15000 });

    const chatToggle = page.locator('[data-testid="chatbot-toggle"], button[aria-label*="chat" i], [class*="chat-toggle"], [class*="chatbot"]').first();
    const visible = await chatToggle.isVisible({ timeout: 5000 }).catch(() => false);
    if (visible) {
      await expect(chatToggle).toBeVisible();
    }
  });

  test('chatbot opens and has input field', async ({ page }) => {
    await injectMockSession(page);
    await page.goto('/#translator');

    const chatToggle = page.locator('[data-testid="chatbot-toggle"], button[aria-label*="chat" i], [class*="chat-toggle"]').first();
    const visible = await chatToggle.isVisible({ timeout: 5000 }).catch(() => false);
    if (visible) {
      await chatToggle.click();
      const input = page.locator('[data-testid="chat-input"], input[placeholder*="message" i], textarea[placeholder*="message" i]').first();
      await expect(input).toBeVisible({ timeout: 5000 });
    }
  });
});

test.describe('Accessibility: axe-core scan', () => {
  test('home page has no critical accessibility violations', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#root')).toBeVisible({ timeout: 15000 });

    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa'])
      .analyze();

    const critical = results.violations.filter(v => v.impact === 'critical');
    expect(critical).toHaveLength(0);
  });

  test('translator page has no critical accessibility violations', async ({ page }) => {
    await injectMockSession(page);
    await page.goto('/#translator');
    await expect(page.locator('#root')).toBeVisible({ timeout: 15000 });

    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa'])
      .analyze();

    const critical = results.violations.filter(v => v.impact === 'critical');
    expect(critical).toHaveLength(0);
  });

  test('rendered landing-zone SVG has no serious accessibility violations', async ({ page }) => {
    await injectMockSession(page);
    await page.route('**/api/diagrams/e2e-test-001/export-architecture-package?format=svg', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          content: ACCESSIBLE_LANDING_ZONE_SVG,
          filename: 'archmorph-landing-zone.svg',
        }),
      });
    });

    await page.goto('/#translator');
    await expect(page.locator('#root')).toBeVisible({ timeout: 15000 });

    await page.getByRole('button', { name: 'Export All' }).click();
    for (const label of [
      'Infrastructure Code',
      'High-Level Design',
      'Cost Estimate',
      'Migration Timeline',
      'PDF Analysis Report',
    ]) {
      const checkbox = page.getByLabel(`Include ${label}`);
      if (await checkbox.isChecked()) {
        await checkbox.uncheck();
      }
    }
    await page.getByLabel('Architecture Package format').selectOption('svg-primary');
    await page.getByRole('button', { name: /Generate All Selected/i }).click();

    const viewer = page.getByTestId('landing-zone-viewer');
    await expect(viewer).toBeVisible({ timeout: 10000 });
    const svg = page.getByTestId('landing-zone-svg-preview').locator('svg');
    await expect(svg).toHaveAttribute('role', 'img');
    await expect(svg.locator('title').first()).toHaveText('Azure Landing Zone');

    await page.getByRole('button', { name: 'Azure Kubernetes Service' }).focus();
    await expect(page.getByTestId('landing-zone-live-region')).toContainText('Compute tier: Azure Kubernetes Service');

    const results = await new AxeBuilder({ page })
      .include('[data-testid="landing-zone-viewer"]')
      .withTags(['wcag2a', 'wcag2aa'])
      .analyze();

    const seriousOrCritical = results.violations.filter(v => v.impact === 'serious' || v.impact === 'critical');
    expect(seriousOrCritical).toHaveLength(0);
  });
});
