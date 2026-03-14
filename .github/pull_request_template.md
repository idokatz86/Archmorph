## Description

<!-- What does this PR do? Why is this change needed? -->

## Type of Change

- [ ] Bug fix (non-breaking change fixing an issue)
- [ ] New feature (non-breaking change adding functionality)
- [ ] Breaking change (fix or feature causing existing functionality to change)
- [ ] Refactor (no functional changes)
- [ ] Documentation update
- [ ] CI/CD or infrastructure change
- [ ] Dependency update

## Related Issues

<!-- Link to GitHub issues: Fixes #123, Closes #456 -->

## Testing

- [ ] Unit tests added/updated
- [ ] All existing tests pass (`pytest` + `vitest`)
- [ ] Manual testing performed (describe below)
- [ ] E2E tests pass (`npx playwright test` — if UI changes)

## Definition of Done Checklist

### Code Quality
- [ ] PR title follows Semantic Pull Request format (`feat:`, `fix:`, `chore:`, etc.)
- [ ] Code follows project style guidelines (ruff, ESLint)
- [ ] Self-review completed
- [ ] No `console.log` / debug prints left in production code
- [ ] No TODO/FIXME without a linked issue

### Security
- [ ] No secrets or credentials in code
- [ ] No breaking API changes (or versioned appropriately)
- [ ] Input validation on all new endpoints
- [ ] XSS/injection risks reviewed for user-facing inputs

### Testing Thresholds
- [ ] Backend test coverage ≥ 80% for changed files
- [ ] Frontend test coverage ≥ 70% for changed files
- [ ] Generated IaC passes `terraform validate` (if IaC changes)

### Observability
- [ ] Logging added for new error paths
- [ ] Metrics/counters updated (if new user-facing flow)

### Documentation
- [ ] API docs updated (if new/changed endpoints)
- [ ] README / CHANGELOG updated (if user-visible change)

### Accessibility (if UI changes)
- [ ] WCAG 2.1 AA compliant (contrast, focus, keyboard nav)
- [ ] Screen reader tested (VoiceOver / NVDA)

### Deployment Readiness
- [ ] Alembic migration included (if schema change)
- [ ] Feature flag wrapped (if gradual rollout needed)
- [ ] Rollback plan identified

## Screenshots / Evidence

<!-- If applicable, add screenshots or test output -->
