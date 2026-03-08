import datetime
from typing import List, Dict, Any, Optional
from azure.identity import DefaultAzureCredential, ClientSecretCredential
from azure.mgmt.resourcegraph import ResourceGraphClient
from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions
from azure.mgmt.subscription import SubscriptionClient

from models.infrastructure import (
    LiveArchitectureSchema,
    CloudResource,
    ScanMetadata,
    CloudProvider,
    ResourceType
)

# A very basic mapping from Azure resource provider types to Archmorph ResourceTypes
AZURE_TYPE_MAPPING = {
    "microsoft.compute": ResourceType.COMPUTE,
    "microsoft.network": ResourceType.NETWORKING,
    "microsoft.storage": ResourceType.STORAGE,
    "microsoft.sql": ResourceType.DATABASE,
    "microsoft.dbforpostgresql": ResourceType.DATABASE,
    "microsoft.dbformysql": ResourceType.DATABASE,
    "microsoft.documentdb": ResourceType.DATABASE,
    "microsoft.cache": ResourceType.DATABASE,
    "microsoft.kusto": ResourceType.DATABASE,
    "microsoft.web": ResourceType.WEB,
    "microsoft.containerservice": ResourceType.COMPUTE,
    "microsoft.containerregistry": ResourceType.DEVOPS,
    "microsoft.app": ResourceType.COMPUTE,
    "microsoft.batch": ResourceType.COMPUTE,
    "microsoft.classiccompute": ResourceType.COMPUTE,
    "microsoft.servicebus": ResourceType.MESSAGING,
    "microsoft.eventhub": ResourceType.MESSAGING,
    "microsoft.eventgrid": ResourceType.MESSAGING,
    "microsoft.logic": ResourceType.MESSAGING,
    "microsoft.apimanagement": ResourceType.MESSAGING,
    "microsoft.signalrservice": ResourceType.MESSAGING,
    "microsoft.cognitiveservices": ResourceType.AI_ML,
    "microsoft.machinelearningservices": ResourceType.AI_ML,
    "microsoft.search": ResourceType.AI_ML,
    "microsoft.synapse": ResourceType.ANALYTICS,
    "microsoft.datafactory": ResourceType.ANALYTICS,
    "microsoft.databricks": ResourceType.ANALYTICS,
    "microsoft.streamanalytics": ResourceType.ANALYTICS,
    "microsoft.powerbidedicated": ResourceType.ANALYTICS,
    "microsoft.insights": ResourceType.DEVOPS,
    "microsoft.operationalinsights": ResourceType.DEVOPS,
    "microsoft.keyvault": ResourceType.SECURITY,
    "microsoft.authorization": ResourceType.IDENTITY,
}

class AzureScanner:
    """
    Scans an Azure environment to discover active infrastructure resources.
    Uses Azure Resource Graph for comprehensive and fast retrieval.
    """
    def __init__(self, credentials: Optional[Dict[str, str]] = None):
        if credentials and "tenant_id" in credentials and "client_id" in credentials and "client_secret" in credentials:
            self.credential = ClientSecretCredential(
                tenant_id=credentials["tenant_id"],
                client_id=credentials["client_id"],
                client_secret=credentials["client_secret"]
            )
        else:
            self.credential = DefaultAzureCredential()

    def perform_full_scan(self) -> Dict[str, Any]:
        """
        Executes a scan against the available Azure subscriptions 
        and returns a dictionary matching the LiveArchitectureSchema.
        """
        schema = self.scan()
        return schema.model_dump()

    def get_subscriptions(self) -> List[str]:
        """Fetch all subscriptions accessible by the current credential."""
        sub_client = SubscriptionClient(self.credential)
        return [sub.subscription_id for sub in sub_client.subscriptions.list()]

    def map_azure_type(self, resource_type: str) -> ResourceType:
        """Map Azure specific types (e.g. microsoft.compute/virtualmachines) to Archmorph ResourceType."""
        provider = resource_type.split("/")[0].lower() if "/" in resource_type else resource_type.lower()
        return AZURE_TYPE_MAPPING.get(provider, ResourceType.OTHER)

    def scan(self, subscription_ids: List[str] = None) -> LiveArchitectureSchema:
        """
        Executes a scan against the specified Azure subscriptions.
        If no subscriptions are provided, discovers and scans all available subscriptions.
        """
        if not subscription_ids:
            subscription_ids = self.get_subscriptions()

        if not subscription_ids:
            # Return empty schema if no subscriptions are accessible
            return LiveArchitectureSchema(
                metadata=ScanMetadata(
                    provider=CloudProvider.AZURE,
                    scanned_regions=[],
                    resource_count=0,
                    scan_timestamp=datetime.datetime.utcnow().isoformat()
                ),
                resources=[]
            )

        client = ResourceGraphClient(self.credential)
        
        # We query for all major resource types, capturing basics + tags + inner properties
        query = """
        Resources
        | project id, name, type, location, tags, properties
        """

        request = QueryRequest(
            subscriptions=subscription_ids,
            query=query,
            options=QueryRequestOptions(result_format="objectArray")
        )

        response = client.resources(request)
        discovered_resources = []
        scanned_regions = set()

        for item in response.data:
            loc = item.get("location", "global")
            scanned_regions.add(loc)
            
            res_type = item.get("type", "unknown")
            attributes = item.get("properties") or {}
            
            # Extract high-level state if present inside properties
            # Different resources map their state differently in properties
            state = "unknown"
            if isinstance(attributes, dict):
                state = attributes.get("provisioningState", attributes.get("status", attributes.get("state", "unknown")))

            cloud_res = CloudResource(
                id=item.get("id"),
                name=item.get("name"),
                type=res_type,
                category=self.map_azure_type(res_type),
                region=loc,
                state=str(state),
                tags=item.get("tags") or {},
                attributes=attributes
            )
            discovered_resources.append(cloud_res)

        return LiveArchitectureSchema(
            metadata=ScanMetadata(
                provider=CloudProvider.AZURE,
                scanned_regions=list(scanned_regions),
                resource_count=len(discovered_resources),
                scan_timestamp=datetime.datetime.utcnow().isoformat()
            ),
            resources=discovered_resources
        )
