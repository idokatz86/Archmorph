from pathlib import Path


REPO_ROOT = Path(__file__).parents[2]
PLAYWRIGHT_CONFIG = REPO_ROOT / "playwright.config.ts"
PLAYWRIGHT_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "playwright.yml"
CORE_FUNNEL_SPEC = REPO_ROOT / "e2e" / "core-funnel.spec.ts"


def test_playwright_config_includes_mobile_chrome_project():
    config = PLAYWRIGHT_CONFIG.read_text(encoding="utf-8")
    workflow = PLAYWRIGHT_WORKFLOW.read_text(encoding="utf-8")

    assert 'name: "mobile-chrome"' in config
    assert 'devices["Pixel 5"]' in config
    assert "--project=mobile-chrome" in workflow


def test_core_funnel_enforces_keyboard_and_color_contrast_accessibility():
    spec = CORE_FUNNEL_SPEC.read_text(encoding="utf-8")

    assert "translator export controls remain visible across mobile viewports" in spec
    assert "export dialog supports keyboard close and returns focus to trigger" in spec
    assert "disableRules(['color-contrast'])" not in spec
