from checkov.common.models.enums import CheckCategories, CheckResult
from checkov.terraform.checks.resource.base_resource_check import BaseResourceCheck


class AzureStorageProdNetworkBypass(BaseResourceCheck):
    def __init__(self):
        name = (
            "Ensure Azure Storage accounts with deny-by-default network rules "
            "include AzureServices in the bypass list"
        )
        check_id = "CKV_ARCHMORPH_5"
        super().__init__(
            name=name,
            id=check_id,
            categories=(CheckCategories.NETWORKING,),
            supported_resources=("azurerm_storage_account",),
        )

    def scan_resource_conf(self, conf):
        network_rules = conf.get("network_rules")
        if not network_rules:
            # No network rules block at all — public by default, no deny-without-path risk
            return CheckResult.PASSED

        rules = network_rules[0] if isinstance(network_rules, list) else network_rules
        if not isinstance(rules, dict):
            return CheckResult.UNKNOWN

        default_action = rules.get("default_action")
        if isinstance(default_action, list) and default_action:
            default_action = default_action[0]
        if str(default_action).lower() != "deny":
            return CheckResult.PASSED

        bypass = rules.get("bypass", [])
        # bypass may be nested in an extra list layer from HCL parsing
        if isinstance(bypass, list) and len(bypass) > 0 and isinstance(bypass[0], list):
            bypass = bypass[0]

        if "AzureServices" in bypass:
            return CheckResult.PASSED
        return CheckResult.FAILED


check = AzureStorageProdNetworkBypass()
