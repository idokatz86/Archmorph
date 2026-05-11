from checkov.common.models.enums import CheckCategories, CheckResult
from checkov.terraform.checks.resource.base_resource_check import BaseResourceCheck


class AzurePostgreSQLNoPublicAccess(BaseResourceCheck):
    def __init__(self):
        name = "Ensure Azure PostgreSQL Flexible Server does not expose public network access"
        check_id = "CKV_ARCHMORPH_2"
        super().__init__(
            name=name,
            id=check_id,
            categories=(CheckCategories.NETWORKING,),
            supported_resources=("azurerm_postgresql_flexible_server",),
        )

    def scan_resource_conf(self, conf):
        public_network_access = conf.get("public_network_access_enabled")
        if not public_network_access:
            return CheckResult.FAILED
        value = public_network_access[0] if isinstance(public_network_access, list) else public_network_access
        if value is False or str(value).lower() == "false":
            return CheckResult.PASSED
        return CheckResult.FAILED


check = AzurePostgreSQLNoPublicAccess()