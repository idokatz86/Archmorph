from checkov.common.models.enums import CheckCategories, CheckResult
from checkov.terraform.checks.resource.base_resource_check import BaseResourceCheck


class AzureStorageInfrastructureEncryption(BaseResourceCheck):
    def __init__(self):
        name = "Ensure Azure Storage accounts use infrastructure encryption"
        check_id = "CKV_ARCHMORPH_3"
        super().__init__(
            name=name,
            id=check_id,
            categories=(CheckCategories.ENCRYPTION,),
            supported_resources=("azurerm_storage_account",),
        )

    def scan_resource_conf(self, conf):
        encryption_enabled = conf.get("infrastructure_encryption_enabled")
        if not encryption_enabled:
            return CheckResult.FAILED
        value = encryption_enabled[0] if isinstance(encryption_enabled, list) else encryption_enabled
        if value is True or str(value).lower() == "true":
            return CheckResult.PASSED
        return CheckResult.FAILED


check = AzureStorageInfrastructureEncryption()