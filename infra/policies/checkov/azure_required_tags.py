from checkov.common.models.enums import CheckCategories, CheckResult
from checkov.terraform.checks.resource.base_resource_check import BaseResourceCheck


class AzureRequiredTags(BaseResourceCheck):
    def __init__(self):
        name = "Ensure taggable Azure resources carry the Archmorph baseline tags"
        check_id = "CKV_ARCHMORPH_1"
        supported_resources = (
            "azurerm_application_insights",
            "azurerm_container_app",
            "azurerm_container_app_environment",
            "azurerm_container_registry",
            "azurerm_key_vault",
            "azurerm_log_analytics_workspace",
            "azurerm_monitor_action_group",
            "azurerm_monitor_scheduled_query_rules_alert_v2",
            "azurerm_postgresql_flexible_server",
            "azurerm_redis_cache",
            "azurerm_resource_group",
            "azurerm_static_web_app",
            "azurerm_storage_account",
            "azurerm_traffic_manager_profile",
        )
        super().__init__(name=name, id=check_id, categories=(CheckCategories.GENERAL_SECURITY,), supported_resources=supported_resources)

    def scan_resource_conf(self, conf):
        tags = conf.get("tags")
        if not tags:
            return CheckResult.FAILED
        tag_block = tags[0] if isinstance(tags, list) else tags
        if isinstance(tag_block, str):
            return CheckResult.PASSED
        required = {"project", "environment", "managed_by"}
        return CheckResult.PASSED if required.issubset(set(tag_block.keys())) else CheckResult.FAILED


check = AzureRequiredTags()