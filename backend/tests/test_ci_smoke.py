import ci_smoke


def test_ci_smoke_hld_generation_avoids_openai(monkeypatch):
    import hld_generator

    monkeypatch.setenv("ARCHMORPH_CI_SMOKE_MODE", "1")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setattr(
        hld_generator,
        "cached_chat_completion",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("OpenAI should not be called in CI smoke mode")
        ),
    )

    hld = hld_generator.generate_hld(ci_smoke.analysis("diagram-1"))

    assert hld["title"] == "CI Smoke Azure High-Level Design"
    assert hld["services"]
    assert "Azure" in hld_generator.generate_hld_markdown(hld)


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
