"""
Archmorph – Production-Grade IaC Scaffold Generator

Generates a complete Terraform project structure from analysis results:
modules (networking, compute, database, storage, security), per-environment
configs (dev/staging/prod), CI/CD pipeline, Makefile, and README.

No external dependencies beyond the Python stdlib.
"""

import logging
import json
from typing import Dict, List, Optional

from prompt_guard import sanitize_iac_param, _VALID_REGIONS
from traceability_map import build_traceability_map

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Service categorization
# ─────────────────────────────────────────────────────────────
_CATEGORY_MAP: Dict[str, str] = {
    # Compute
    "virtual machine": "compute",
    "vm": "compute",
    "vmss": "compute",
    "container app": "compute",
    "container apps": "compute",
    "app service": "compute",
    "function app": "compute",
    "functions": "compute",
    "aks": "compute",
    "kubernetes": "compute",
    "batch": "compute",
    "container instances": "compute",
    "aci": "compute",
    "spring apps": "compute",
    "web app": "compute",
    # Database
    "sql": "database",
    "azure sql": "database",
    "postgresql": "database",
    "cosmos db": "database",
    "cosmosdb": "database",
    "mysql": "database",
    "mariadb": "database",
    "redis": "database",
    "cache for redis": "database",
    "sql server": "database",
    "sql database": "database",
    # Storage
    "storage account": "storage",
    "blob storage": "storage",
    "blob": "storage",
    "file share": "storage",
    "data lake": "storage",
    "queue storage": "storage",
    "table storage": "storage",
    "cdn": "storage",
    # Networking
    "virtual network": "networking",
    "vnet": "networking",
    "load balancer": "networking",
    "application gateway": "networking",
    "front door": "networking",
    "dns zone": "networking",
    "private endpoint": "networking",
    "nat gateway": "networking",
    "vpn gateway": "networking",
    "expressroute": "networking",
    "firewall": "networking",
    "bastion": "networking",
    "traffic manager": "networking",
    "nsg": "networking",
    "network security group": "networking",
    # Security
    "key vault": "security",
    "managed identity": "security",
    "service principal": "security",
    "rbac": "security",
    "azure ad": "security",
    "entra id": "security",
    "defender": "security",
    "sentinel": "security",
    "monitor": "security",
    "log analytics": "security",
    "application insights": "security",
}


def _categorize_service(service_name: str, category_hint: str = "") -> str:
    """Classify a service into a module category."""
    hint = category_hint.lower().strip()
    if hint in ("compute", "database", "storage", "networking", "security"):
        return hint

    name = service_name.lower()
    for keyword, cat in _CATEGORY_MAP.items():
        if keyword in name:
            return cat

    return "compute"  # default bucket


def _group_services(mappings: List[dict]) -> Dict[str, List[dict]]:
    """Group analysis mappings by module category."""
    groups: Dict[str, List[dict]] = {
        "networking": [],
        "compute": [],
        "database": [],
        "storage": [],
        "security": [],
    }
    for m in mappings:
        azure_svc = m.get("azure_service", m.get("target_service", "unknown"))
        cat = _categorize_service(azure_svc, m.get("category", ""))
        groups[cat].append(m)
    return groups


# ─────────────────────────────────────────────────────────────
# Resource block generators (deterministic HCL — no LLM call)
# ─────────────────────────────────────────────────────────────

_RESOURCE_TEMPLATES: Dict[str, str] = {
    # Compute
    "app service": """\
resource "azurerm_service_plan" "${{name}}_plan" {{
  name                = "${{prefix}}-asp-${{svc_suffix}}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  os_type             = "Linux"
  sku_name            = var.app_service_sku

  tags = local.common_tags
}}

resource "azurerm_linux_web_app" "${{name}}" {{
  name                = "${{prefix}}-app-${{svc_suffix}}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  service_plan_id     = azurerm_service_plan.${{name}}_plan.id

  site_config {{
    always_on = var.environment == "prod" ? true : false
  }}

  identity {{
    type = "SystemAssigned"
  }}

  tags = local.common_tags
}}
""",
    "function app": """\
resource "azurerm_service_plan" "${{name}}_plan" {{
  name                = "${{prefix}}-func-plan-${{svc_suffix}}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  os_type             = "Linux"
  sku_name            = var.function_sku

  tags = local.common_tags
}}

resource "azurerm_linux_function_app" "${{name}}" {{
  name                       = "${{prefix}}-func-${{svc_suffix}}"
  resource_group_name        = azurerm_resource_group.main.name
  location                   = azurerm_resource_group.main.location
  service_plan_id            = azurerm_service_plan.${{name}}_plan.id
  storage_account_name       = var.storage_account_name
  storage_account_access_key = var.storage_account_access_key

  site_config {{}}

  identity {{
    type = "SystemAssigned"
  }}

  tags = local.common_tags
}}
""",
    "container app": """\
resource "azurerm_container_app_environment" "${{name}}_env" {{
  name                = "${{prefix}}-cae-${{svc_suffix}}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location

  tags = local.common_tags
}}

resource "azurerm_container_app" "${{name}}" {{
  name                         = "${{prefix}}-ca-${{svc_suffix}}"
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.${{name}}_env.id
  revision_mode                = "Single"

  template {{
    container {{
      name   = "${{svc_suffix}}"
      image  = "mcr.microsoft.com/hello-world-app:latest"
      cpu    = var.container_cpu
      memory = var.container_memory
    }}
  }}

  tags = local.common_tags
}}
""",
    "virtual machine": """\
resource "azurerm_linux_virtual_machine" "${{name}}" {{
  name                  = "${{prefix}}-vm-${{svc_suffix}}"
  resource_group_name   = azurerm_resource_group.main.name
  location              = azurerm_resource_group.main.location
  size                  = var.vm_size
  admin_username        = "azureadmin"
  network_interface_ids = [var.nic_id]

  admin_ssh_key {{
    username   = "azureadmin"
    public_key = var.ssh_public_key
  }}

  os_disk {{
    caching              = "ReadWrite"
    storage_account_type = "Premium_LRS"
  }}

  source_image_reference {{
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts-gen2"
    version   = "latest"
  }}

  identity {{
    type = "SystemAssigned"
  }}

  tags = local.common_tags
}}
""",
    "aks": """\
resource "azurerm_kubernetes_cluster" "${{name}}" {{
  name                = "${{prefix}}-aks-${{svc_suffix}}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  dns_prefix          = "${{prefix}}-aks"

  default_node_pool {{
    name       = "default"
    node_count = var.aks_node_count
    vm_size    = var.aks_vm_size
  }}

  identity {{
    type = "SystemAssigned"
  }}

  tags = local.common_tags
}}
""",
    # Database
    "azure sql": """\
resource "azurerm_mssql_server" "${{name}}" {{
  name                         = "${{prefix}}-sql-${{svc_suffix}}"
  resource_group_name          = azurerm_resource_group.main.name
  location                     = azurerm_resource_group.main.location
  version                      = "12.0"
  minimum_tls_version          = "1.2"

  azuread_administrator {{
    login_username = var.sql_aad_admin_login
    object_id      = var.sql_aad_admin_object_id
  }}

  tags = local.common_tags
}}

resource "azurerm_mssql_database" "${{name}}_db" {{
  name      = "${{prefix}}-sqldb-${{svc_suffix}}"
  server_id = azurerm_mssql_server.${{name}}.id
  sku_name  = var.sql_sku

  tags = local.common_tags
}}
""",
    "postgresql": """\
resource "azurerm_postgresql_flexible_server" "${{name}}" {{
  name                          = "${{prefix}}-pg-${{svc_suffix}}"
  resource_group_name           = azurerm_resource_group.main.name
  location                      = azurerm_resource_group.main.location
  version                       = "16"
  sku_name                      = var.pg_sku
  storage_mb                    = var.pg_storage_mb
  zone                          = "1"

  authentication {{
    active_directory_auth_enabled = true
    password_auth_enabled         = false
    tenant_id                     = var.tenant_id
  }}

  tags = local.common_tags
}}
""",
    "cosmos db": """\
resource "azurerm_cosmosdb_account" "${{name}}" {{
  name                = "${{prefix}}-cosmos-${{svc_suffix}}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  offer_type          = "Standard"
  kind                = "GlobalDocumentDB"

  consistency_policy {{
    consistency_level = "Session"
  }}

  geo_location {{
    location          = azurerm_resource_group.main.location
    failover_priority = 0
  }}

  tags = local.common_tags
}}
""",
    "redis": """\
resource "azurerm_redis_cache" "${{name}}" {{
  name                = "${{prefix}}-redis-${{svc_suffix}}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  capacity            = var.redis_capacity
  family              = var.redis_family
  sku_name            = var.redis_sku
  minimum_tls_version = "1.2"

  redis_configuration {{}}

  tags = local.common_tags
}}
""",
    # Storage
    "storage account": """\
resource "azurerm_storage_account" "${{name}}" {{
  name                     = "${{safe_name}}"
  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  account_tier             = var.storage_tier
  account_replication_type = var.storage_replication
  min_tls_version          = "TLS1_2"

  blob_properties {{
    delete_retention_policy {{
      days = 7
    }}
  }}

  tags = local.common_tags
}}
""",
    "blob storage": """\
resource "azurerm_storage_account" "${{name}}" {{
  name                     = "${{safe_name}}"
  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  account_tier             = var.storage_tier
  account_replication_type = var.storage_replication
  min_tls_version          = "TLS1_2"

  blob_properties {{
    delete_retention_policy {{
      days = 7
    }}
  }}

  tags = local.common_tags
}}
""",
    # Networking
    "virtual network": """\
resource "azurerm_virtual_network" "${{name}}" {{
  name                = "${{prefix}}-vnet-${{svc_suffix}}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  address_space       = var.vnet_address_space

  tags = local.common_tags
}}

resource "azurerm_subnet" "${{name}}_default" {{
  name                 = "default"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.${{name}}.name
  address_prefixes     = var.subnet_prefixes
}}
""",
    "application gateway": """\
resource "azurerm_application_gateway" "${{name}}" {{
  name                = "${{prefix}}-agw-${{svc_suffix}}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location

  sku {{
    name     = var.agw_sku
    tier     = var.agw_tier
    capacity = var.agw_capacity
  }}

  gateway_ip_configuration {{
    name      = "gateway-ip-config"
    subnet_id = var.agw_subnet_id
  }}

  frontend_port {{
    name = "http"
    port = 80
  }}

  frontend_ip_configuration {{
    name                 = "frontend"
    public_ip_address_id = var.agw_public_ip_id
  }}

  backend_address_pool {{
    name = "default"
  }}

  backend_http_settings {{
    name                  = "default"
    cookie_based_affinity = "Disabled"
    port                  = 80
    protocol              = "Http"
    request_timeout       = 30
  }}

  http_listener {{
    name                           = "default"
    frontend_ip_configuration_name = "frontend"
    frontend_port_name             = "http"
    protocol                       = "Http"
  }}

  request_routing_rule {{
    name                       = "default"
    priority                   = 100
    rule_type                  = "Basic"
    http_listener_name         = "default"
    backend_address_pool_name  = "default"
    backend_http_settings_name = "default"
  }}

  tags = local.common_tags
}}
""",
    "load balancer": """\
resource "azurerm_lb" "${{name}}" {{
  name                = "${{prefix}}-lb-${{svc_suffix}}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "Standard"

  tags = local.common_tags
}}
""",
    # Security
    "key vault": """\
resource "azurerm_key_vault" "${{name}}" {{
  name                        = "${{prefix}}-kv-${{svc_suffix}}"
  resource_group_name         = azurerm_resource_group.main.name
  location                    = azurerm_resource_group.main.location
  tenant_id                   = var.tenant_id
  sku_name                    = "standard"
  purge_protection_enabled    = true
  soft_delete_retention_days  = 90
  enable_rbac_authorization   = true

  network_acls {{
    default_action = "Deny"
    bypass         = "AzureServices"
  }}

  tags = local.common_tags
}}
""",
    "managed identity": """\
resource "azurerm_user_assigned_identity" "${{name}}" {{
  name                = "${{prefix}}-id-${{svc_suffix}}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location

  tags = local.common_tags
}}
""",
    "log analytics": """\
resource "azurerm_log_analytics_workspace" "${{name}}" {{
  name                = "${{prefix}}-law-${{svc_suffix}}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "PerGB2018"
  retention_in_days   = var.log_retention_days

  tags = local.common_tags
}}
""",
}


def _safe_tf_name(s: str) -> str:
    """Convert a service name to a Terraform-safe identifier."""
    import re as _re
    name = _re.sub(r'[^a-z0-9_]', '_', s.lower())
    name = _re.sub(r'_+', '_', name).strip('_')
    if name and name[0].isdigit():
        name = "svc_" + name
    return name or "svc"


def _safe_storage_name(prefix: str) -> str:
    """Generate a storage-account-safe name (lowercase, no hyphens, <=24 chars)."""
    import re as _re
    clean = _re.sub(r'[^a-z0-9]', '', prefix.lower())
    return (clean + "st")[:24]


def _match_template(service_name: str) -> Optional[str]:
    """Find the best matching resource template key for a service name."""
    lower = service_name.lower()
    for key in _RESOURCE_TEMPLATES:
        if key in lower:
            return key
    return None


# ─────────────────────────────────────────────────────────────
# Module file generators
# ─────────────────────────────────────────────────────────────

def _generate_module_main(category: str, services: List[dict], project_name: str) -> str:
    """Generate main.tf for a module."""
    prefix = "${var.project_name}-${var.environment}"
    lines = [
        f'# Module: {category}',
        '# Auto-generated by Archmorph IaC Scaffold Generator',
        '',
        'locals {',
        '  common_tags = {',
        '    project     = var.project_name',
        '    environment = var.environment',
        '    managed_by  = "terraform"',
        '    module      = "%s"' % category,
        '  }',
        '}',
        '',
    ]

    seen_templates: set = set()
    idx = 0
    for svc in services:
        azure_name = svc.get("azure_service", svc.get("target_service", "unknown"))
        source_name = svc.get("source_service", "")
        tpl_key = _match_template(azure_name)
        if not tpl_key or tpl_key in seen_templates:
            continue
        seen_templates.add(tpl_key)

        tf_name = _safe_tf_name(tpl_key)
        svc_suffix = _safe_tf_name(tpl_key)
        safe_name = _safe_storage_name(project_name)

        tpl = _RESOURCE_TEMPLATES[tpl_key]
        block = tpl.replace("${name}", tf_name)
        block = block.replace("${prefix}", prefix)
        block = block.replace("${svc_suffix}", svc_suffix)
        block = block.replace("${safe_name}", safe_name)

        if source_name:
            lines.append(f"# Replaces: {source_name}")
        lines.append(block)
        idx += 1

    if idx == 0:
        lines.append(f"# No specific {category} resources detected — add resources here")
        lines.append("")

    return "\n".join(lines)


def _generate_module_variables(category: str, services: List[dict]) -> str:
    """Generate variables.tf for a module."""
    base = """\
variable "project_name" {
  description = "Project name used in resource naming"
  type        = string
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
}

variable "resource_group_name" {
  description = "Name of the resource group"
  type        = string
}

variable "location" {
  description = "Azure region"
  type        = string
}

variable "tenant_id" {
  description = "Azure AD tenant ID"
  type        = string
  sensitive   = true
}
"""
    extra_vars: Dict[str, str] = {}
    for svc in services:
        azure_name = (svc.get("azure_service", "") or "").lower()
        if "app service" in azure_name or "web app" in azure_name:
            extra_vars["app_service_sku"] = 'variable "app_service_sku" {\n  description = "App Service plan SKU"\n  type        = string\n  default     = "B1"\n}\n'
        if "function" in azure_name:
            extra_vars["function_sku"] = 'variable "function_sku" {\n  description = "Function App plan SKU"\n  type        = string\n  default     = "Y1"\n}\n'
            extra_vars["storage_account_name"] = 'variable "storage_account_name" {\n  description = "Storage account name for Function App"\n  type        = string\n}\n'
            extra_vars["storage_account_access_key"] = 'variable "storage_account_access_key" {\n  description = "Storage account access key"\n  type        = string\n  sensitive   = true\n}\n'
        if "container app" in azure_name:
            extra_vars["container_cpu"] = 'variable "container_cpu" {\n  description = "Container CPU allocation"\n  type        = number\n  default     = 0.5\n}\n'
            extra_vars["container_memory"] = 'variable "container_memory" {\n  description = "Container memory allocation"\n  type        = string\n  default     = "1Gi"\n}\n'
        if "virtual machine" in azure_name or "vm" in azure_name:
            extra_vars["vm_size"] = 'variable "vm_size" {\n  description = "VM size"\n  type        = string\n  default     = "Standard_B2s"\n}\n'
            extra_vars["nic_id"] = 'variable "nic_id" {\n  description = "Network interface ID"\n  type        = string\n}\n'
            extra_vars["ssh_public_key"] = 'variable "ssh_public_key" {\n  description = "SSH public key for VM admin"\n  type        = string\n  sensitive   = true\n}\n'
        if "aks" in azure_name or "kubernetes" in azure_name:
            extra_vars["aks_node_count"] = 'variable "aks_node_count" {\n  description = "AKS default node pool count"\n  type        = number\n  default     = 2\n}\n'
            extra_vars["aks_vm_size"] = 'variable "aks_vm_size" {\n  description = "AKS node VM size"\n  type        = string\n  default     = "Standard_D2s_v3"\n}\n'
        if "sql" in azure_name:
            extra_vars["sql_sku"] = 'variable "sql_sku" {\n  description = "Azure SQL Database SKU"\n  type        = string\n  default     = "S0"\n}\n'
            extra_vars["sql_aad_admin_login"] = 'variable "sql_aad_admin_login" {\n  description = "Azure AD admin login for SQL"\n  type        = string\n}\n'
            extra_vars["sql_aad_admin_object_id"] = 'variable "sql_aad_admin_object_id" {\n  description = "Azure AD admin object ID"\n  type        = string\n}\n'
        if "postgresql" in azure_name:
            extra_vars["pg_sku"] = 'variable "pg_sku" {\n  description = "PostgreSQL Flexible Server SKU"\n  type        = string\n  default     = "B_Standard_B1ms"\n}\n'
            extra_vars["pg_storage_mb"] = 'variable "pg_storage_mb" {\n  description = "PostgreSQL storage in MB"\n  type        = number\n  default     = 32768\n}\n'
        if "cosmos" in azure_name:
            pass  # no extra vars needed
        if "redis" in azure_name:
            extra_vars["redis_capacity"] = 'variable "redis_capacity" {\n  description = "Redis cache capacity"\n  type        = number\n  default     = 1\n}\n'
            extra_vars["redis_family"] = 'variable "redis_family" {\n  description = "Redis cache family"\n  type        = string\n  default     = "C"\n}\n'
            extra_vars["redis_sku"] = 'variable "redis_sku" {\n  description = "Redis cache SKU"\n  type        = string\n  default     = "Basic"\n}\n'
        if "storage" in azure_name or "blob" in azure_name:
            extra_vars["storage_tier"] = 'variable "storage_tier" {\n  description = "Storage account tier"\n  type        = string\n  default     = "Standard"\n}\n'
            extra_vars["storage_replication"] = 'variable "storage_replication" {\n  description = "Storage replication type"\n  type        = string\n  default     = "LRS"\n}\n'
        if "virtual network" in azure_name or "vnet" in azure_name:
            extra_vars["vnet_address_space"] = 'variable "vnet_address_space" {\n  description = "Virtual network address space"\n  type        = list(string)\n  default     = ["10.0.0.0/16"]\n}\n'
            extra_vars["subnet_prefixes"] = 'variable "subnet_prefixes" {\n  description = "Default subnet address prefixes"\n  type        = list(string)\n  default     = ["10.0.1.0/24"]\n}\n'
        if "application gateway" in azure_name:
            extra_vars["agw_sku"] = 'variable "agw_sku" {\n  description = "Application Gateway SKU name"\n  type        = string\n  default     = "Standard_v2"\n}\n'
            extra_vars["agw_tier"] = 'variable "agw_tier" {\n  description = "Application Gateway tier"\n  type        = string\n  default     = "Standard_v2"\n}\n'
            extra_vars["agw_capacity"] = 'variable "agw_capacity" {\n  description = "Application Gateway capacity"\n  type        = number\n  default     = 2\n}\n'
            extra_vars["agw_subnet_id"] = 'variable "agw_subnet_id" {\n  description = "Subnet ID for Application Gateway"\n  type        = string\n}\n'
            extra_vars["agw_public_ip_id"] = 'variable "agw_public_ip_id" {\n  description = "Public IP ID for Application Gateway"\n  type        = string\n}\n'
        if "key vault" in azure_name:
            pass  # tenant_id already in base
        if "log analytics" in azure_name:
            extra_vars["log_retention_days"] = 'variable "log_retention_days" {\n  description = "Log Analytics retention in days"\n  type        = number\n  default     = 30\n}\n'

    return base + "\n" + "\n".join(extra_vars.values())


def _generate_module_outputs(category: str, services: List[dict]) -> str:
    """Generate outputs.tf for a module."""
    lines = [f"# Outputs for {category} module", ""]

    seen: set = set()
    for svc in services:
        azure_name = (svc.get("azure_service", "") or "").lower()
        tpl_key = _match_template(azure_name)
        if not tpl_key or tpl_key in seen:
            continue
        seen.add(tpl_key)
        tf_name = _safe_tf_name(tpl_key)

        if "app service" in tpl_key or "web app" in tpl_key:
            lines.append(f'output "{tf_name}_hostname" {{\n  value = azurerm_linux_web_app.{tf_name}.default_hostname\n}}\n')
        elif "function" in tpl_key:
            lines.append(f'output "{tf_name}_hostname" {{\n  value = azurerm_linux_function_app.{tf_name}.default_hostname\n}}\n')
        elif "container app" in tpl_key:
            lines.append(f'output "{tf_name}_fqdn" {{\n  value = azurerm_container_app.{tf_name}.latest_revision_fqdn\n}}\n')
        elif "aks" in tpl_key or "kubernetes" in tpl_key:
            lines.append(f'output "{tf_name}_kube_config" {{\n  value     = azurerm_kubernetes_cluster.{tf_name}.kube_config_raw\n  sensitive = true\n}}\n')
        elif "sql" in tpl_key:
            lines.append(f'output "{tf_name}_fqdn" {{\n  value = azurerm_mssql_server.{tf_name}.fully_qualified_domain_name\n}}\n')
        elif "postgresql" in tpl_key:
            lines.append(f'output "{tf_name}_fqdn" {{\n  value = azurerm_postgresql_flexible_server.{tf_name}.fqdn\n}}\n')
        elif "cosmos" in tpl_key:
            lines.append(f'output "{tf_name}_endpoint" {{\n  value = azurerm_cosmosdb_account.{tf_name}.endpoint\n}}\n')
        elif "redis" in tpl_key:
            lines.append(f'output "{tf_name}_hostname" {{\n  value = azurerm_redis_cache.{tf_name}.hostname\n}}\n')
        elif "storage" in tpl_key or "blob" in tpl_key:
            lines.append(f'output "{tf_name}_primary_blob_endpoint" {{\n  value = azurerm_storage_account.{tf_name}.primary_blob_endpoint\n}}\n')
        elif "virtual network" in tpl_key or "vnet" in tpl_key:
            lines.append(f'output "{tf_name}_id" {{\n  value = azurerm_virtual_network.{tf_name}.id\n}}\n')
        elif "key vault" in tpl_key:
            lines.append(f'output "{tf_name}_uri" {{\n  value = azurerm_key_vault.{tf_name}.vault_uri\n}}\n')
        elif "log analytics" in tpl_key:
            lines.append(f'output "{tf_name}_workspace_id" {{\n  value = azurerm_log_analytics_workspace.{tf_name}.workspace_id\n}}\n')
        else:
            lines.append(f'# output "{tf_name}_id" — add appropriate output reference')
            lines.append("")

    if len(seen) == 0:
        lines.append(f"# No outputs for {category} — add as resources are defined")
        lines.append("")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# Environment config generators
# ─────────────────────────────────────────────────────────────

_ENV_SKUS = {
    "dev": {
        "app_service_sku": "B1",
        "function_sku": "Y1",
        "vm_size": "Standard_B2s",
        "sql_sku": "S0",
        "pg_sku": "B_Standard_B1ms",
        "redis_sku": "Basic",
        "redis_family": "C",
        "redis_capacity": 1,
        "storage_replication": "LRS",
        "aks_node_count": 1,
        "aks_vm_size": "Standard_B2s",
        "container_cpu": 0.25,
        "container_memory": "0.5Gi",
        "pg_storage_mb": 32768,
        "log_retention_days": 30,
    },
    "staging": {
        "app_service_sku": "S1",
        "function_sku": "S1",
        "vm_size": "Standard_D2s_v3",
        "sql_sku": "S1",
        "pg_sku": "GP_Standard_D2s_v3",
        "redis_sku": "Standard",
        "redis_family": "C",
        "redis_capacity": 2,
        "storage_replication": "ZRS",
        "aks_node_count": 2,
        "aks_vm_size": "Standard_D2s_v3",
        "container_cpu": 0.5,
        "container_memory": "1Gi",
        "pg_storage_mb": 65536,
        "log_retention_days": 60,
    },
    "prod": {
        "app_service_sku": "P1v3",
        "function_sku": "EP1",
        "vm_size": "Standard_D4s_v3",
        "sql_sku": "S3",
        "pg_sku": "GP_Standard_D4s_v3",
        "redis_sku": "Premium",
        "redis_family": "P",
        "redis_capacity": 1,
        "storage_replication": "GRS",
        "aks_node_count": 3,
        "aks_vm_size": "Standard_D4s_v3",
        "container_cpu": 1.0,
        "container_memory": "2Gi",
        "pg_storage_mb": 131072,
        "log_retention_days": 90,
    },
}


def _generate_env_main(env: str, categories_with_services: Dict[str, List[dict]], project_name: str, region: str) -> str:
    """Generate main.tf for an environment that calls modules."""
    lines = [
        f"# Environment: {env}",
        "# Auto-generated by Archmorph IaC Scaffold Generator",
        "",
        "terraform {",
        '  required_version = ">= 1.5"',
        "",
        "  required_providers {",
        "    azurerm = {",
        '      source  = "hashicorp/azurerm"',
        '      version = "~> 4.0"',
        "    }",
        "  }",
        "}",
        "",
        "provider \"azurerm\" {",
        "  features {}",
        "}",
        "",
        'resource "azurerm_resource_group" "main" {',
        '  name     = "${var.project_name}-${var.environment}-rg"',
        '  location = var.location',
        "",
        "  tags = {",
        '    project     = var.project_name',
        '    environment = var.environment',
        '    managed_by  = "terraform"',
        "  }",
        "}",
        "",
        'variable "project_name" {',
        '  type    = string',
        f'  default = "{project_name}"',
        '}',
        "",
        'variable "environment" {',
        '  type    = string',
        f'  default = "{env}"',
        '}',
        "",
        'variable "location" {',
        '  type    = string',
        f'  default = "{region}"',
        '}',
        "",
        'variable "tenant_id" {',
        '  description = "Azure AD tenant ID"',
        '  type        = string',
        '  sensitive   = true',
        '}',
        "",
    ]

    for cat, svcs in categories_with_services.items():
        if not svcs:
            continue
        lines.append(f'module "{cat}" {{')
        lines.append(f'  source = "../../modules/{cat}"')
        lines.append("")
        lines.append('  project_name        = var.project_name')
        lines.append('  environment         = var.environment')
        lines.append('  resource_group_name = azurerm_resource_group.main.name')
        lines.append('  location            = var.location')
        lines.append('  tenant_id           = var.tenant_id')
        lines.append("}")
        lines.append("")

    return "\n".join(lines)


def _generate_env_tfvars(env: str, project_name: str, region: str) -> str:
    """Generate terraform.tfvars for an environment."""
    skus = _ENV_SKUS.get(env, _ENV_SKUS["dev"])
    lines = [
        f'# {env} environment variables',
        '# Auto-generated by Archmorph IaC Scaffold Generator',
        "",
        f'project_name = "{project_name}"',
        f'environment  = "{env}"',
        f'location     = "{region}"',
        "",
        "# SKU / sizing configuration",
    ]

    for k, v in skus.items():
        if isinstance(v, str):
            lines.append(f'{k} = "{v}"')
        elif isinstance(v, (int, float)):
            lines.append(f'{k} = {v}')

    return "\n".join(lines)


def _generate_backend_tf(env: str, project_name: str) -> str:
    """Generate backend.tf with azurerm remote state config."""
    safe = project_name.replace("-", "").replace("_", "")[:10]
    return f"""\
# Remote state configuration for {env}
# Update the storage account and container names to match your Azure setup
terraform {{
  backend "azurerm" {{
    resource_group_name  = "{project_name}-tfstate-rg"
    storage_account_name = "{safe}tfstate{env}"
    container_name       = "tfstate"
    key                  = "{env}.terraform.tfstate"
  }}
}}
"""


# ─────────────────────────────────────────────────────────────
# CI/CD, Makefile, README, .gitignore
# ─────────────────────────────────────────────────────────────

def _generate_github_workflow(project_name: str) -> str:
    """Generate .github/workflows/terraform.yml."""
    return f"""\
name: "Terraform CI/CD"

on:
  pull_request:
    branches: [main]
    paths: ["terraform/**"]
  push:
    branches: [main]
    paths: ["terraform/**"]

permissions:
  id-token: write
  contents: read
  pull-requests: write

env:
  ARM_CLIENT_ID: ${{{{ secrets.AZURE_CLIENT_ID }}}}
  ARM_SUBSCRIPTION_ID: ${{{{ secrets.AZURE_SUBSCRIPTION_ID }}}}
  ARM_TENANT_ID: ${{{{ secrets.AZURE_TENANT_ID }}}}
  ARM_USE_OIDC: true
  TF_WORKING_DIR: terraform/environments/${{{{ github.event_name == 'push' && 'prod' || 'dev' }}}}

jobs:
  terraform:
    name: "Terraform"
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: ${{{{ env.TF_WORKING_DIR }}}}

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Terraform
        uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: "1.9.x"

      - name: Azure Login (OIDC)
        uses: azure/login@v2
        with:
          client-id: ${{{{ secrets.AZURE_CLIENT_ID }}}}
          tenant-id: ${{{{ secrets.AZURE_TENANT_ID }}}}
          subscription-id: ${{{{ secrets.AZURE_SUBSCRIPTION_ID }}}}

      - name: Terraform Init
        run: terraform init

      - name: Terraform Format Check
        run: terraform fmt -check -recursive

      - name: Terraform Validate
        run: terraform validate

      - name: Terraform Plan
        id: plan
        run: terraform plan -no-color -out=tfplan
        continue-on-error: true

      - name: Upload Plan Artifact
        if: github.event_name == 'pull_request'
        uses: actions/upload-artifact@v4
        with:
          name: tfplan-${{{{ github.sha }}}}
          path: ${{{{ env.TF_WORKING_DIR }}}}/tfplan
          retention-days: 5

      - name: Comment PR with Plan
        if: github.event_name == 'pull_request'
        uses: actions/github-script@v7
        with:
          script: |
            const output = `#### Terraform Plan
            **Project:** {project_name}
            **Environment:** ${{{{ env.TF_WORKING_DIR }}}}
            **Status:** ${{{{ steps.plan.outcome }}}}

            <details><summary>Show Plan</summary>

            ${{{{ steps.plan.outputs.stdout }}}}

            </details>

            *Pushed by: @${{{{ github.actor }}}}*`;

            github.rest.issues.createComment({{
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: output
            }});

      - name: Terraform Apply
        if: github.ref == 'refs/heads/main' && github.event_name == 'push'
        run: terraform apply -auto-approve tfplan
"""


def _generate_makefile() -> str:
    """Generate Makefile for local terraform operations."""
    return """\
# Archmorph IaC Scaffold — Makefile
# Usage: make plan ENV=dev

ENV ?= dev
TF_DIR = environments/$(ENV)

.PHONY: init plan apply destroy validate fmt lint clean

init:
\t@echo "== Terraform Init ($(ENV)) =="
\tcd $(TF_DIR) && terraform init

plan: init
\t@echo "== Terraform Plan ($(ENV)) =="
\tcd $(TF_DIR) && terraform plan -out=tfplan

apply: init
\t@echo "== Terraform Apply ($(ENV)) =="
\tcd $(TF_DIR) && terraform apply tfplan

destroy: init
\t@echo "== Terraform Destroy ($(ENV)) =="
\tcd $(TF_DIR) && terraform destroy

validate:
\t@echo "== Terraform Validate =="
\t@for dir in environments/*/; do \\
\t\techo "Validating $$dir..."; \\
\t\tcd $$dir && terraform validate && cd ../..; \\
\tdone

fmt:
\t@echo "== Terraform Format =="
\tterraform fmt -recursive .

lint:
\t@echo "== TFLint =="
\ttflint --recursive

clean:
\t@echo "== Cleaning build artifacts =="
\tfind . -name "tfplan" -delete
\tfind . -name ".terraform.lock.hcl" -delete
\tfind . -type d -name ".terraform" -exec rm -rf {} + 2>/dev/null || true
"""


def _generate_gitignore() -> str:
    """Generate .gitignore for Terraform projects."""
    return """\
# Terraform
*.tfstate
*.tfstate.*
*.tfplan
tfplan
.terraform/
.terraform.lock.hcl
crash.log
crash.*.log
override.tf
override.tf.json
*_override.tf
*_override.tf.json
*.tfvars.json

# IDE
.idea/
.vscode/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Secrets — never commit
*.pem
*.key
"""


def _generate_readme(project_name: str, categories_with_services: Dict[str, List[dict]]) -> str:
    """Generate README.md with usage instructions."""
    module_list = ""
    for cat, svcs in categories_with_services.items():
        if svcs:
            svc_names = ", ".join(
                s.get("azure_service", s.get("target_service", "unknown"))
                for s in svcs
            )
            module_list += f"- **{cat}**: {svc_names}\n"
        else:
            module_list += f"- **{cat}**: (no services detected)\n"

    return f"""\
# {project_name} — Terraform Infrastructure

Auto-generated by [Archmorph](https://archmorphai.com) IaC Scaffold Generator.

## Modules

{module_list}

## Environments

| Environment | SKUs | HA | Geo-Redundancy |
|-------------|------|----|----------------|
| dev         | Small (B-series) | No | No |
| staging     | Medium (S/D-series) | Basic | No |
| prod        | Production (P/D-series) | Full | Yes (GRS) |

## Quick Start

```bash
# Initialize dev environment
make init ENV=dev

# Plan changes
make plan ENV=dev

# Apply changes
make apply ENV=dev

# Format and validate
make fmt
make validate
```

## Remote State

Each environment uses Azure Storage for remote state.
Create the backend resources first:

```bash
az group create -n {project_name}-tfstate-rg -l westeurope
az storage account create -n {project_name.replace('-', '')[:10]}tfstatedev -g {project_name}-tfstate-rg -l westeurope --sku Standard_LRS
az storage container create -n tfstate --account-name {project_name.replace('-', '')[:10]}tfstatedev
```

## CI/CD

GitHub Actions workflow in `.github/workflows/terraform.yml`:
- **PR**: runs `terraform plan` and posts the output as a comment
- **Push to main**: runs `terraform apply`
- Uses **OIDC** for Azure authentication (no stored secrets)

### Required GitHub Secrets

| Secret | Description |
|--------|-------------|
| `AZURE_CLIENT_ID` | Service principal / managed identity client ID |
| `AZURE_TENANT_ID` | Azure AD tenant ID |
| `AZURE_SUBSCRIPTION_ID` | Target subscription ID |

## Security

- All credentials stored in Azure Key Vault
- Managed Identity used where possible
- No inline passwords — Entra ID auth for databases
- TLS 1.2+ enforced on all resources
- Network ACLs default to Deny
"""


# ─────────────────────────────────────────────────────────────
# Main scaffold generator
# ─────────────────────────────────────────────────────────────

def generate_scaffold(
    analysis: Optional[dict],
    params: Optional[dict] = None,
) -> Dict[str, str]:
    """Generate a complete Terraform project scaffold from analysis results.

    Args:
        analysis: Diagram analysis result with mappings, services_detected, etc.
        params: Optional dict with project_name, region, environment keys.

    Returns:
        Dict mapping relative file paths to their content.
        Example: {"terraform/modules/compute/main.tf": "resource ..."}
    """
    params = params or {}
    mappings = (analysis or {}).get("mappings", [])

    project_name = sanitize_iac_param(
        params.get("project_name", "cloud-migration"),
        "project_name",
        default="cloud-migration",
    )
    region = sanitize_iac_param(
        params.get("region", "westeurope"),
        "region",
        allowed_values=_VALID_REGIONS,
        default="westeurope",
    )

    # Group services into module categories
    groups = _group_services(mappings)

    # Always ensure security module has Key Vault + Managed Identity
    security_names = {(s.get("azure_service", "") or "").lower() for s in groups["security"]}
    if not any("key vault" in n for n in security_names):
        groups["security"].append({
            "azure_service": "Key Vault",
            "source_service": "(auto-added for credential management)",
            "category": "security",
        })
    if not any("managed identity" in n for n in security_names):
        groups["security"].append({
            "azure_service": "Managed Identity",
            "source_service": "(auto-added for identity-based auth)",
            "category": "security",
        })
    if not any("log analytics" in n for n in security_names):
        groups["security"].append({
            "azure_service": "Log Analytics",
            "source_service": "(auto-added for observability)",
            "category": "security",
        })

    files: Dict[str, str] = {}

    # ── Modules ──
    for cat, svcs in groups.items():
        prefix = f"terraform/modules/{cat}"
        files[f"{prefix}/main.tf"] = _generate_module_main(cat, svcs, project_name)
        files[f"{prefix}/variables.tf"] = _generate_module_variables(cat, svcs)
        files[f"{prefix}/outputs.tf"] = _generate_module_outputs(cat, svcs)

    # ── Environments ──
    for env in ("dev", "staging", "prod"):
        prefix = f"terraform/environments/{env}"
        files[f"{prefix}/main.tf"] = _generate_env_main(env, groups, project_name, region)
        files[f"{prefix}/terraform.tfvars"] = _generate_env_tfvars(env, project_name, region)
        files[f"{prefix}/backend.tf"] = _generate_backend_tf(env, project_name)

    # ── CI/CD ──
    files["terraform/.github/workflows/terraform.yml"] = _generate_github_workflow(project_name)

    # ── Supporting files ──
    files["terraform/Makefile"] = _generate_makefile()
    files["terraform/.gitignore"] = _generate_gitignore()
    files["terraform/traceability-map.json"] = json.dumps(
      build_traceability_map(analysis),
      indent=2,
      sort_keys=True,
    ) + "\n"
    files["terraform/README.md"] = _generate_readme(project_name, groups)

    logger.info(
        "IaC scaffold generated: %d files, modules=%s, project=%s",
        len(files),
        [c for c, s in groups.items() if s],
        project_name,
    )

    return files
