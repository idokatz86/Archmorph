import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const SAMPLE_PDF_BUFFER = Buffer.from(
  '%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n',
);

test.describe('Shared button accessibility', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/.auth/me', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ clientPrincipal: null }),
      });
    });
    await page.route('**/api/auth/me', async route => {
      await route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Not authenticated' }),
      });
    });
  });

  test('supports keyboard activation and has no serious or critical axe violations', async ({ page }) => {
    await page.goto('/#translator');
    await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toHaveAttribute(
      'type',
      'button',
    );
    await page.locator('input[type="file"]').setInputFiles({
      name: 'architecture.pdf',
      mimeType: 'application/pdf',
      buffer: SAMPLE_PDF_BUFFER,
    });
    await expect(page.getByText('architecture.pdf')).toBeVisible();

    const signInButton = page.getByRole('button', { name: 'Sign in to analyze' });
    await expect(signInButton).toHaveAttribute('type', 'button');
    await signInButton.focus();
    await page.keyboard.press('Enter');
    const dialog = page.getByRole('dialog', { name: /sign in to archmorph/i });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole('button', { name: /^close$/i })).toBeFocused();
    await page.keyboard.press('Escape');
    await expect(dialog).toBeHidden();
    await expect(signInButton).toBeFocused();
    await signInButton.evaluate(button => {
      button.setAttribute('data-axe-target', 'shared-button');
    });

    const results = await new AxeBuilder({ page })
      .include('[data-axe-target="shared-button"]')
      .withTags(['wcag2a', 'wcag2aa'])
      .analyze();

    const seriousOrCritical = results.violations.filter(
      violation => violation.impact === 'serious' || violation.impact === 'critical',
    );
    expect(seriousOrCritical).toHaveLength(0);
  });
});
