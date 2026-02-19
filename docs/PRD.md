# Archmorph – Cloud Architecture Translator to Azure
## Product Requirements Document (PRD)
**Version:** 1.1  
**Date:** February 19, 2026  
**Author:** Ido Katz  

---

## 1. Executive Summary

Archmorph is an AI-powered tool that converts AWS and GCP architecture diagrams into Azure equivalents. It analyzes uploaded diagrams, identifies cloud services, maps them to Azure counterparts, and generates ready-to-deploy Terraform/Bicep infrastructure code.

**Problem:** Organizations migrating to Azure spend weeks manually mapping source architecture to Azure services. This process is error-prone and requires deep multi-cloud expertise.

**Solution:** Automated diagram analysis and service translation with confidence-scored mappings and generated IaC.

---

## 2. Target Users

| Persona | Role | Primary Need |
|---------|------|--------------|
| **Cloud Architect** | Solution design | Validate migration feasibility quickly |
| **DevOps Engineer** | Infrastructure automation | Generate deployable IaC from diagrams |
| **Technical Manager** | Migration planning | Estimate effort and identify gaps |
| **Consultant** | Multi-cloud advisory | Rapid proposal generation for clients |

---

## 3. Core Features

### 3.1 Diagram Upload & Analysis
- **Supported formats:** PNG, JPG, SVG, PDF, Draw.io (.drawio), Lucidchart export
- **Visio (.vsdx):** Phase 3 (complex parsing)
- **Max file size:** 25 MB
- **Analysis time:** ≤30 seconds for diagrams ≤50 services

### 3.2 Service Detection
- AI-powered identification using Azure OpenAI GPT-4 Vision
- Detects: Services, connections/data flows, annotations
- **Multi-pass analysis:** Diagrams with >30 services trigger 2-pass analysis (quadrant split + merge)

### 3.3 Service Mapping
- Maps detected services to Azure equivalents
- Confidence scores: Critical (≥90%), High (70-89%), Medium (50-69%), Low (<50%)
- **Manual intervention flags** for services with <60% confidence or no direct equivalent

### 3.4 IaC Generation
- **Terraform (HCL):** Primary output
- **Bicep:** Secondary output
- **Scope:** Greenfield deployments only
- **Import blocks:** Phase 3 feature for existing resource adoption
- Read-only code preview with syntax highlighting (Prism.js)

### 3.5 Cost Estimation
- Uses Azure Retail Prices API (`https://prices.azure.com/api/retail/prices`)
- Provides monthly cost estimate range (low/medium/high usage)
- Displays cost per service with total

### 3.6 Export Options
- Download generated IaC (.tf, .bicep)
- Export mapping report (PDF, JSON)
- Copy to clipboard

---

## 4. Service Mapping Database

### 4.1 AWS → Azure Mappings (Core)

| AWS Service | Azure Equivalent | Confidence | Notes |
|-------------|------------------|------------|-------|
| EC2 | Virtual Machines | 95% | Direct mapping |
| S3 | Blob Storage | 95% | Direct mapping |
| RDS | Azure SQL / PostgreSQL Flexible | 90% | Engine-specific |
| Lambda | Azure Functions | 90% | Consumption model |
| DynamoDB | Cosmos DB | 85% | NoSQL, different consistency models |
| EKS | AKS | 90% | Managed Kubernetes |
| API Gateway | API Management | 85% | Feature parity varies |
| CloudFront | Front Door / CDN | 85% | Combined services |
| SQS | Service Bus Queues | 90% | Direct mapping |
| SNS | Service Bus Topics / Event Grid | 80% | Depends on use case |
| Cognito | Azure AD B2C | 75% | Different auth model |
| Step Functions | Logic Apps / Durable Functions | 80% | Depends on workflow |
| Secrets Manager | Key Vault | 95% | Direct mapping |
| Aurora Serverless | Azure SQL Serverless | 70% | Manual review flag |

### 4.2 GCP → Azure Mappings (Core)

| GCP Service | Azure Equivalent | Confidence | Notes |
|-------------|------------------|------------|-------|
| Compute Engine | Virtual Machines | 95% | Direct mapping |
| Cloud Storage | Blob Storage | 95% | Direct mapping |
| Cloud SQL | Azure SQL / PostgreSQL Flexible | 90% | Engine-specific |
| Cloud Functions | Azure Functions | 90% | Direct mapping |
| GKE | AKS | 90% | Managed Kubernetes |
| Pub/Sub | Service Bus / Event Grid | 85% | Pub/Sub model |
| BigQuery | Synapse Analytics | 80% | Different pricing model |
| Cloud Run | Container Apps | 90% | Serverless containers |
| Firestore | Cosmos DB | 85% | Document DB |
| Secret Manager | Key Vault | 95% | Direct mapping |
| Workflows | Logic Apps | 80% | YAML vs designer |
| Spanner | Cosmos DB (distributed) | 70% | Manual review flag |

### 4.3 Mapping Governance Process

| Activity | Frequency | Owner |
|----------|-----------|-------|
| New service additions | Monthly | Product team |
| Confidence score recalibration | Quarterly | Engineering |
| Deprecation review | Quarterly | Product team |
| Community contribution review | Bi-weekly | Maintainers |

**Versioning:** Mappings stored in `mappings/v{MAJOR}.{MINOR}.json` with changelog.

---

## 5. Authentication & Authorization

### 5.1 Authentication Methods

| Method | Use Case | Details |
|--------|----------|---------|
| **Azure AD (B2B)** | Enterprise users | SSO via tenant federation |
| **Microsoft Account** | Individual users | Consumer sign-in |
| **API Keys** | CI/CD automation | Phase 3, scoped to project |

### 5.2 Authorization Levels

| Role | Permissions |
|------|-------------|
| Viewer | View projects, download exports |
| Editor | Upload diagrams, run analysis |
| Admin | Manage team, API keys, billing |

### 5.3 API Key Management (Phase 3)
- Keys scoped per project
- Rate limits: 100 requests/hour (standard), 1000/hour (enterprise)
- Rotation: Manual + auto-expire after 90 days

---

## 6. Error Handling & Edge Cases

### 6.1 Analysis Errors

| Scenario | User Message | System Behavior |
|----------|--------------|-----------------|
| Unrecognized service icon | "1 service could not be identified" | Mark as `UNKNOWN`, allow manual mapping |
| Blurry/low-res diagram | "Image quality too low for reliable analysis" | Show preview, allow retry |
| No services detected | "No cloud services found in this diagram" | Suggest supported formats |
| Timeout (>60s) | "Analysis taking longer than expected" | Background job, notify on completion |
| Unsupported format | "This file format is not supported" | List supported formats |

### 6.2 Mapping Errors

| Scenario | Handling |
|----------|----------|
| No Azure equivalent exists | Flag as "Manual Intervention Required", suggest closest alternative |
| Deprecated source service | Show warning, map to replacement if known |
| Ambiguous service (e.g., generic "database" icon) | Prompt user to select from options |

### 6.3 IaC Generation Errors

| Scenario | Handling |
|----------|----------|
| Service missing required config | Generate placeholder with `# TODO: Configure X` |
| Circular dependencies detected | Warning banner, manual reordering suggested |

---

## 7. Non-Functional Requirements

| Requirement | Target | Phase |
|-------------|--------|-------|
| Analysis latency | ≤30s for ≤50 services | MVP |
| Availability | 99.5% uptime | MVP |
| Max diagram size | 25 MB | MVP |
| Max services per diagram | 50 | MVP |
| Max services per project | 200 (across multiple diagrams) | MVP |
| Concurrent analyses | 10 per user | MVP |
| Data retention | 90 days (free), unlimited (paid) | MVP |
| **Accessibility** | WCAG 2.1 AA | MVP |

---

## 8. Technical Architecture

### 8.1 Stack

| Layer | Technology |
|-------|------------|
| Frontend | React 18, Vite, TailwindCSS, Prism.js (syntax highlighting) |
| Backend | Python 3.11, FastAPI |
| AI | Azure OpenAI GPT-4 Vision |
| Database | PostgreSQL (Azure Flexible Server) |
| Storage | Azure Blob Storage |
| Hosting | Azure Container Apps (API), Static Web Apps (frontend) |
| IaC | Terraform (infra), Bicep support in-app |

### 8.2 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/projects` | POST | Create project |
| `/api/projects/{id}/diagrams` | POST | Upload diagram |
| `/api/diagrams/{id}/analyze` | POST | Trigger analysis |
| `/api/diagrams/{id}/mappings` | GET | Get service mappings |
| `/api/diagrams/{id}/mappings/{svc}` | PATCH | Override mapping |
| `/api/diagrams/{id}/generate` | POST | Generate IaC |
| `/api/diagrams/{id}/export` | GET | Download IaC/report |
| `/api/health` | GET | Health check |

---

## 9. Roadmap

| Phase | Milestone | Features |
|-------|-----------|----------|
| **MVP (Q2 2026)** | Public Beta | Diagram upload, AWS→Azure mapping, Terraform output |
| **Phase 2 (Q3 2026)** | GCP Support | GCP→Azure mapping, Bicep output, cost estimation |
| **Phase 3 (Q4 2026)** | Enterprise | Visio support, API keys, import blocks, SSO |
| **Phase 4 (2027)** | Advanced | Pulumi output, Azure Migrate integration, multi-diagram projects |

---

## 10. Success Metrics

| Metric | Target (MVP) | Target (GA) |
|--------|--------------|-------------|
| Analysis accuracy | ≥85% services correctly identified | ≥92% |
| Mapping accuracy | ≥90% correct Azure equivalent | ≥95% |
| Time to first IaC export | ≤5 minutes | ≤3 minutes |
| User retention (30-day) | ≥40% | ≥60% |

---

## 11. Open Items

| Item | Decision | Owner |
|------|----------|-------|
| Pricing model | Usage-based (per diagram) with 5 free/month | PM |
| Pulumi support | Phase 4 | Engineering |
| Azure Migrate partnership | Phase 4, requires BD | PM |

---

*End of Document*
