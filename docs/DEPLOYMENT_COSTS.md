# Archmorph – Azure Deployment Costs

**Region:** West Europe  
**Last Updated:** February 19, 2026

---

## Summary

| Environment | Monthly Estimate | Annual Estimate |
|-------------|------------------|-----------------|
| **Development/Test** | $180 – $250 | $2,160 – $3,000 |
| **Production (Small)** | $500 – $800 | $6,000 – $9,600 |
| **Production (Enterprise)** | $1,500 – $3,000 | $18,000 – $36,000 |

---

## Detailed Cost Breakdown

### 1. Azure Container Apps (Backend API)

| Tier | vCPU | Memory | Requests/Month | Cost/Month |
|------|------|--------|----------------|------------|
| **Dev/Test** | 0.5 | 1 GB | 10,000 | ~$15 |
| **Production** | 2.0 | 4 GB | 100,000 | ~$80 |
| **Enterprise** | 4.0 | 8 GB | 1,000,000 | ~$250 |

**Notes:**
- Consumption tier pricing (pay-per-use)
- Scale to zero when idle (dev/test)
- Includes ingress costs

---

### 2. Azure Static Web Apps (Frontend)

| Tier | Features | Cost/Month |
|------|----------|------------|
| **Free** | 100 GB bandwidth, custom domain, SSL | $0 |
| **Standard** | Unlimited bandwidth, SLA, private endpoints | $9 |

**Recommendation:** Free tier for MVP, Standard for production.

---

### 3. Azure OpenAI Service (GPT-4 Vision)

| Model | Input Tokens | Output Tokens | Cost per 1K Tokens |
|-------|--------------|---------------|-------------------|
| **GPT-4 Vision** | Prompt | Completion | $0.01 / $0.03 |

**Estimated Usage:**

| Scenario | Diagrams/Month | Avg Tokens/Diagram | Cost/Month |
|----------|----------------|-------------------|------------|
| **Dev/Test** | 100 | 5,000 | ~$25 |
| **Production** | 1,000 | 5,000 | ~$200 |
| **Enterprise** | 10,000 | 5,000 | ~$1,800 |

**Notes:**
- Multi-pass analysis for complex diagrams increases token usage
- Cache common patterns to reduce repeated analysis

---

### 4. Azure Database for PostgreSQL (Flexible Server)

| Tier | vCores | Storage | Cost/Month |
|------|--------|---------|------------|
| **Burstable B1ms** | 1 | 32 GB | ~$25 |
| **General Purpose D2s_v3** | 2 | 128 GB | ~$120 |
| **Memory Optimized E4s_v3** | 4 | 256 GB | ~$350 |

**Recommendation:**
- Dev/Test: Burstable B1ms ($25)
- Production: General Purpose D2s_v3 ($120)

**Additional Costs:**
- Backup storage: $0.095/GB/month
- High availability: +100% base cost

---

### 5. Azure Blob Storage

| Tier | Capacity | Operations | Cost/Month |
|------|----------|------------|------------|
| **Hot** | 50 GB | 100,000 | ~$5 |
| **Hot** | 500 GB | 1,000,000 | ~$25 |
| **Cool** | 1 TB | 500,000 | ~$15 |

**Storage Use Cases:**
- Uploaded diagrams (PNG, SVG, PDF)
- Generated IaC files
- Exported reports

---

### 6. Azure Container Registry (ACR)

| Tier | Storage | Builds | Cost/Month |
|------|---------|--------|------------|
| **Basic** | 10 GB | 2/day | ~$5 |
| **Standard** | 100 GB | 10/day | ~$20 |

**Recommendation:** Basic tier for all environments.

---

### 7. Azure Key Vault

| Operations/Month | Cost |
|------------------|------|
| 10,000 | ~$1 |
| 100,000 | ~$3 |

**Note:** Minimal cost; used for secrets and API keys.

---

### 8. Azure Log Analytics

| Ingestion | Retention | Cost/Month |
|-----------|-----------|------------|
| 5 GB | 30 days | $0 (free tier) |
| 50 GB | 90 days | ~$115 |
| 200 GB | 90 days | ~$460 |

**Recommendation:**
- Dev/Test: Free tier (5 GB)
- Production: 50 GB with 90-day retention

---

### 9. Networking

| Component | Cost/Month |
|-----------|------------|
| Public IP (Static) | ~$4 |
| NAT Gateway | ~$32 |
| Private Endpoints (per endpoint) | ~$7.50 |

**Note:** Container Apps include ingress; separate costs only for advanced networking.

---

## Cost Optimization Strategies

### Development/Test
1. Use consumption-based Container Apps (scale to zero)
2. Free tier Static Web Apps
3. Burstable PostgreSQL tier
4. Limit OpenAI requests with dev API quota

### Production
1. Reserved capacity for PostgreSQL (1-year: 30% savings)
2. Blob lifecycle policies (move to Cool tier after 30 days)
3. Implement response caching to reduce OpenAI calls
4. Use scheduled scaling for Container Apps

### Enterprise
1. Azure Reservations (1-3 year) for all compute
2. Enterprise Agreement pricing
3. Commitment-based OpenAI pricing
4. Multi-region with Traffic Manager (add ~30% for DR)

---

## Monthly Cost Summary Tables

### Development/Test Environment

| Service | SKU | Cost/Month |
|---------|-----|------------|
| Container Apps | Consumption 0.5 vCPU | $15 |
| Static Web Apps | Free | $0 |
| Azure OpenAI | 100 diagrams | $25 |
| PostgreSQL | Burstable B1ms | $25 |
| Blob Storage | Hot 50 GB | $5 |
| Container Registry | Basic | $5 |
| Key Vault | Standard | $1 |
| Log Analytics | Free tier | $0 |
| **Total** | | **$76 – $100** |

*Add buffer for variable usage: **~$180 – $250/month***

---

### Production Environment (Small)

| Service | SKU | Cost/Month |
|---------|-----|------------|
| Container Apps | Consumption 2 vCPU | $80 |
| Static Web Apps | Standard | $9 |
| Azure OpenAI | 1,000 diagrams | $200 |
| PostgreSQL | D2s_v3 + HA | $240 |
| Blob Storage | Hot 500 GB | $25 |
| Container Registry | Standard | $20 |
| Key Vault | Standard | $3 |
| Log Analytics | 50 GB | $115 |
| **Total** | | **$692** |

*Add 15% buffer: **~$500 – $800/month***

---

### Production Environment (Enterprise)

| Service | SKU | Cost/Month |
|---------|-----|------------|
| Container Apps | 4 vCPU × 3 replicas | $750 |
| Static Web Apps | Standard | $9 |
| Azure OpenAI | 10,000 diagrams | $1,800 |
| PostgreSQL | E4s_v3 + HA | $700 |
| Blob Storage | Hot 2 TB | $50 |
| Container Registry | Premium | $50 |
| Key Vault | Premium + HSM | $15 |
| Log Analytics | 200 GB | $460 |
| Private Endpoints | 4 endpoints | $30 |
| **Total** | | **$3,864** |

*With reservations (30% off compute): **~$2,500 – $3,000/month***

---

## Free Tier Optimization

Services with meaningful free tiers:

| Service | Free Allowance |
|---------|---------------|
| Static Web Apps | 100 GB bandwidth |
| Blob Storage | First 5 GB |
| Log Analytics | First 5 GB/month |
| Container Apps | First 180,000 vCPU·s/month |
| Azure AD B2C | First 50,000 MAU |

**Dev/Test True Minimum:** ~$50-75/month (using all free tiers)

---

## Cost Monitoring

Recommended Azure Cost Management setup:

1. **Budget Alerts:**
   - 50% threshold → Email
   - 80% threshold → Email + Teams
   - 100% threshold → Email + SMS + PagerDuty

2. **Resource Tags:**
   ```
   environment: dev | staging | prod
   project: archmorph
   owner: team-email
   cost-center: engineering
   ```

3. **Monthly Review:**
   - Azure Advisor cost recommendations
   - Unused resource cleanup
   - Right-sizing analysis

---

*Prices based on Azure West Europe region, February 2026. Actual costs may vary.*
