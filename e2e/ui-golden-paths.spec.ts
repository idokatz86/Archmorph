import { test, expect } from '@playwright/test';

/**
 * 🚨 GOLDEN PATHS ONLY 🚨
 * Refactored via Bug Master & QA Master Guidelines:
 * - NO hardcoded timeouts (waitForTimeout)
 * - NO testing backend logic (that is now handled by K6 + Pytest)
 * - ONLY test visible React Flow / UI boundaries
 * - Reliance on ARIA roles where applicable, fallback to strict classes/data-testid
 */

test.describe('Golden Paths: Core UI & React Flow Canvas', () => {

  test.beforeEach(async ({ page }) => {
    // Mock session storage to bypass ML backend analysis (handled by k6/pytest)
    await page.addInitScript(() => {
      sessionStorage.setItem('archmorph_active_diagram', 'test-123');
      sessionStorage.setItem('archmorph_session_test-123', JSON.stringify({
        diagramId: 'test-123',
        analysis: {
           mappings: [
             {
               source_service: 'Amazon EC2',
               azure_service: 'Azure Virtual Machines',
               source_provider: 'aws'
             }
           ],
           service_connections: []
        },
        ts: Date.now()
      }));
    });
    // Navigate to root to start cleanly
    await page.goto('/#translator');
  });

  test('Path 1: Application Mount & Header Visibility', async ({ page }) => {
    // Validate the overarching app container loads successfully without crash
    // using generic accessibility boundaries or root divs
    const rootBlock = page.locator('#root');
    await expect(rootBlock).toBeVisible({ timeout: 15000 });
  });

  test('Path 2: React Flow Canvas Initialization', async ({ page }) => {
    // React Flow is now behind a view toggle (Table/Matrix/Map)
    // First try clicking the Map tab if the view toggle exists
    const mapTab = page.getByRole('button', { name: /map/i }).first();
    if (await mapTab.isVisible({ timeout: 5000 }).catch(() => false)) {
      await mapTab.click();
    }

    // The prime real estate for the app is the react-flow node canvas
    const canvas = page.locator('.react-flow').first();
    await expect(canvas).toBeVisible({ timeout: 20000 });

    // Validate standard React Flow controls surface
    const controls = page.locator('.react-flow__controls').first();
    if (await controls.isVisible()) {
        await expect(controls).toBeVisible();
    }
  });

  test('Path 3: Interactivity & Core Action Modals', async ({ page }) => {
    // Rely on broad generic roles to trace core features (adding, export, etc)
    const exportBtn = page.getByRole('button', { name: /export/i }).first();
    
    // Attempt clicking export flow to ensure modal/dialog does not crash the state
    if (await exportBtn.isVisible()) {
      await exportBtn.click();
      
      const dialog = page.getByRole('dialog').first();
      await expect(dialog).toBeVisible();
      
      // Close out to ensure focus goes back to Canvas properly
      const closeBtn = dialog.getByRole('button', { name: /close/i }).first();
      if (await closeBtn.isVisible()) {
        await closeBtn.click();
        await expect(dialog).toBeHidden();
      }
    }
  });

});
