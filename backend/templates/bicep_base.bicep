// ============================================================
// Archmorph – Azure Infrastructure as Code (Bicep)
// Auto-generated from architecture diagram analysis
// ============================================================

targetScope = 'subscription'

@description('Environment name')
param env string = '{{ENVIRONMENT}}'

@description('Primary Azure region')
param location string = '{{REGION}}'

var project = '{{PROJECT_NAME}}'
var tags = {
  Project: '{{PROJECT_NAME}}'
  ManagedBy: 'Archmorph'
  Environment: env
  Source: 'Cloud-Migration'
}

// ── Resource Group ─────────────────────────────────────────
resource rg 'Microsoft.Resources/resourceGroups@2023-07-01' = {
  name: 'rg-${project}-${env}'
  location: location
  tags: tags
}
