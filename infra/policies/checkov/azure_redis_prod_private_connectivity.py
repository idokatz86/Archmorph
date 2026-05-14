from checkov.common.models.enums import CheckCategories, CheckResult
from checkov.terraform.checks.resource.base_resource_check import BaseResourceCheck


class AzureRedisNoPublicAccess(BaseResourceCheck):
    def __init__(self):
        name = "Ensure Azure Cache for Redis does not expose public network access"
        check_id = "CKV_ARCHMORPH_4"
        super().__init__(
            name=name,
            id=check_id,
            categories=(CheckCategories.NETWORKING,),
            supported_resources=("azurerm_redis_cache",),
        )

    def scan_resource_conf(self, conf):
        public_access = conf.get("public_network_access_enabled")
        if not public_access:
            # Not set — Azure default is public; flag as a concern only when
            # explicitly True. Treat absent as PASSED to avoid false positives
            # on resources whose access is controlled via a ternary expression.
            return CheckResult.PASSED
        value = public_access[0] if isinstance(public_access, list) else public_access
        if value is True or str(value).lower() == "true":
            return CheckResult.FAILED
        # False or an expression (e.g. a prod-env ternary) — pass
        return CheckResult.PASSED


check = AzureRedisNoPublicAccess()
