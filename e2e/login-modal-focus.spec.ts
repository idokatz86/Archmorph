import { test, expect } from '@playwright/test';

test.describe('Accessibility: Login modal keyboard focus order', () => {
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

  test('traps Tab order inside LoginModal and restores focus on Escape', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#root')).toBeVisible({ timeout: 15000 });

    const signInTrigger = page.getByRole('button', { name: /^sign in$/i });
    await expect(signInTrigger).toBeVisible();
    await signInTrigger.focus();
    await expect(signInTrigger).toBeFocused();

    await page.keyboard.press('Enter');
    const dialog = page.getByRole('dialog', { name: /sign in to archmorph/i });
    await expect(dialog).toBeVisible();

    const closeButton = dialog.getByRole('button', { name: /^close$/i });
    const microsoftButton = dialog.getByRole('button', { name: /continue with microsoft/i });
    const googleButton = dialog.getByRole('button', { name: /continue with google/i });
    const githubButton = dialog.getByRole('button', { name: /continue with github/i });
    const guestButton = dialog.getByRole('button', { name: /continue browsing/i });

    await expect(closeButton).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(microsoftButton).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(googleButton).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(githubButton).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(guestButton).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(closeButton).toBeFocused();

    await page.keyboard.press('Shift+Tab');
    await expect(guestButton).toBeFocused();

    await page.keyboard.press('Escape');
    await expect(dialog).toBeHidden();
    await expect(signInTrigger).toBeFocused();
    await expect(signInTrigger).toHaveAttribute('aria-expanded', 'false');
  });
});
