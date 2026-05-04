import ci_smoke


def test_ci_smoke_requires_non_production_environment(monkeypatch):
    monkeypatch.setenv("ARCHMORPH_CI_SMOKE_MODE", "1")

    monkeypatch.setenv("ENVIRONMENT", "production")
    assert ci_smoke.enabled() is False

    monkeypatch.setenv("ENVIRONMENT", "test")
    assert ci_smoke.enabled() is True


def test_ci_smoke_disabled_without_flag(monkeypatch):
    monkeypatch.delenv("ARCHMORPH_CI_SMOKE_MODE", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "test")

    assert ci_smoke.enabled() is False
