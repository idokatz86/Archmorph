# Archived Modules

**Archived:** March 4, 2026  
**Reason:** Feature pruning for PMF focus — reduce surface area from 49→22 backend modules

These modules are **not deleted**. They are working code with tests, archived until
user demand justifies re-integration.

## Re-integration Rules

1. **Demand signal required** — at least 5 user requests or 1 enterprise contract asking for the feature
2. **Copy module back** to its original location
3. **Re-add import + include_router** in `main.py`
4. **Re-add test file** from `_archive/tests/`
5. **Run full test suite** before merging

## What's Archived

### Self-Contained Feature Modules (own router, zero dependents)
| Module | Lines | What it does | Bring back when… |
|--------|-------|-------------|------------------|
| `living_architecture.py` | 322 | Drift detection / health monitoring | You have live infra connections |
| `migration_intelligence.py` | 289 | Community confidence scoring | You have a community (100+ users) |
| `whitelabel.py` | 264 | Partner branding SDK | First partner deal signed |
| `marketplace.py` | 504 | Plugin/template marketplace | Ecosystem exists |
| `journey_analytics.py` | 615 | User journey funnel analytics | Product analytics tool chosen (Mixpanel/Amplitude) |
| `webhooks.py` | 700 | Webhook delivery system | External integrations requested |

### Migration Sub-Features (all accessed via `/api/diagrams/{id}/…`)
| Module | Lines | What it does | Bring back when… |
|--------|-------|-------------|------------------|
| `migration_runbook.py` | 641 | Step-by-step migration task lists | Users complete >50% of generated runbooks |
| `migration_assessment.py` | 547 | Migration complexity scoring | Enterprise migration planning deals |
| `cost_comparison.py` | 225 | Multi-cloud cost comparison | Real pricing data integration |

### Premature Infrastructure
| Module | Lines | What it does | Bring back when… |
|--------|-------|-------------|------------------|
| `generate_icon_packs.py` | 436 | Icon pack generation script | Custom icon packs requested |

### Routers (API surface reduction: 36→25 routers)
| Router | What it does | Bring back when… |
|--------|-------------|------------------|
| `routers/marketplace.py` | Marketplace CRUD API | Marketplace feature needed |
| `routers/journey_analytics.py` | Journey tracking API | Analytics tool integration |
| `routers/webhooks.py` | Webhook management API | Integration partners exist |
| `routers/migration.py` | Runbook/assessment/cost-comparison API | Migration features restored |
| `routers/organizations.py` | Multi-tenancy org management | B2B / team features needed |
| `routers/billing.py` | Stripe billing endpoints | Monetization activated |
| `routers/dashboard.py` | User analysis history API | User accounts + persistence active |
| `routers/templates.py` | Template gallery API | Template library curated |

### Frontend Components
| Component | Lines | Bring back when… |
|-----------|-------|------------------|
| `MonitoringDashboard.jsx` | 405 | Ops monitoring needed |
| `OrganizationSettings.jsx` | 312 | Org/team features |
| `InfraImportPanel.jsx` | 201 | Terraform import is core |
| `CompliancePanel.jsx` | 193 | Enterprise compliance |
| `MigrationRiskPanel.jsx` | 192 | Migration risk scoring used |

### Tests
All corresponding test files are preserved in `_archive/tests/`.
