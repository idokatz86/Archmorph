import datetime
import logging
from typing import Dict, Any, Optional
from google.cloud import asset_v1
from google.oauth2 import service_account
import google.auth

from models.infrastructure import (
    LiveArchitectureSchema,
    CloudResource,
    ScanMetadata,
    CloudProvider,
    ResourceType
)

logger = logging.getLogger(__name__)

# Basic mapping from GCP asset types to Archmorph ResourceType
# Examples of GCP asset types: "compute.googleapis.com/Instance"
GCP_TYPE_MAPPING = {
    "compute.googleapis.com": ResourceType.COMPUTE,
    "container.googleapis.com": ResourceType.COMPUTE,
    "run.googleapis.com": ResourceType.COMPUTE,
    "cloudfunctions.googleapis.com": ResourceType.COMPUTE,
    "storage.googleapis.com": ResourceType.STORAGE,
    "sqladmin.googleapis.com": ResourceType.DATABASE,
    "spanner.googleapis.com": ResourceType.DATABASE,
    "bigtableadmin.googleapis.com": ResourceType.DATABASE,
    "redis.googleapis.com": ResourceType.DATABASE,
    "vpcaccess.googleapis.com": ResourceType.NETWORKING,
    "networkmanagement.googleapis.com": ResourceType.NETWORKING,
    "dns.googleapis.com": ResourceType.NETWORKING,
    "pubsub.googleapis.com": ResourceType.MESSAGING,
    "eventarc.googleapis.com": ResourceType.MESSAGING,
    "iam.googleapis.com": ResourceType.IDENTITY,
    "secretmanager.googleapis.com": ResourceType.SECURITY,
    "bigquery.googleapis.com": ResourceType.ANALYTICS,
    "dataproc.googleapis.com": ResourceType.ANALYTICS,
    "dataflow.googleapis.com": ResourceType.ANALYTICS,
    "aiplatform.googleapis.com": ResourceType.AI_ML,
    "ml.googleapis.com": ResourceType.AI_ML,
    "logging.googleapis.com": ResourceType.DEVOPS,
    "monitoring.googleapis.com": ResourceType.DEVOPS,
    "artifactregistry.googleapis.com": ResourceType.DEVOPS,
}

class GCPScanner:
    """
    Scans a GCP environment to discover active infrastructure resources.
    Uses Google Cloud Asset Inventory for comprehensive coverage.
    """
    def __init__(self, credentials: Optional[Dict[str, str]] = None, project_id: Optional[str] = None):
        self.project_id = project_id
        if credentials and "client_email" in credentials and "private_key" in credentials:
            self.credentials = service_account.Credentials.from_service_account_info(credentials)
            if not self.project_id:
                self.project_id = credentials.get("project_id")
        else:
            self.credentials, default_project = google.auth.default()
            if not self.project_id:
                self.project_id = default_project

    def map_gcp_type(self, asset_type: str) -> ResourceType:
        """Map GCP specific asset types to Archmorph ResourceType."""
        provider = asset_type.split("/")[0] if "/" in asset_type else asset_type
        return GCP_TYPE_MAPPING.get(provider, ResourceType.OTHER)

    def scan(self) -> LiveArchitectureSchema:
        """
        Executes a scan against the GCP project using Cloud Asset API.
        """
        if not self.project_id:
            logger.warning("No GCP project_id available. Returning empty schema.")
            return LiveArchitectureSchema(
                metadata=ScanMetadata(
                    provider=CloudProvider.GCP,
                    scanned_regions=[],
                    resource_count=0,
                    scan_timestamp=datetime.datetime.utcnow().isoformat()
                ),
                resources=[]
            )

        client = asset_v1.AssetServiceClient(credentials=self.credentials)
        parent = f"projects/{self.project_id}"

        # Request to search all supported resources
        # The Asset API provides a `search_all_resources` method which is highly efficient
        try:
            request = asset_v1.SearchAllResourcesRequest(
                scope=parent,
                # Optionally filter for state or regions:
                # query="state:RUNNING"
            )
            
            paged_results = client.search_all_resources(request=request)
            
            discovered_resources = []
            scanned_regions = set()

            for resource in paged_results:
                loc = resource.location or "global"
                scanned_regions.add(loc)

                # Extract useful metadata from the search result
                res_type = resource.asset_type
                
                # 'additional_attributes' is a Struct object, convert it to dict if we need detailed props
                attributes = {
                    "project": resource.project,
                    "description": resource.description,
                    "state": resource.state
                }

                cloud_res = CloudResource(
                    id=resource.name,
                    name=resource.display_name or resource.name.split("/")[-1],
                    type=res_type,
                    category=self.map_gcp_type(res_type),
                    region=loc,
                    state=resource.state or "unknown",
                    tags=dict(resource.labels) if resource.labels else {},
                    attributes=attributes
                )
                discovered_resources.append(cloud_res)

        except Exception as e:
            logger.error(f"Error calling Cloud Asset API: {str(e)}")
            raise e

        return LiveArchitectureSchema(
            metadata=ScanMetadata(
                provider=CloudProvider.GCP,
                scanned_regions=list(scanned_regions),
                resource_count=len(discovered_resources),
                scan_timestamp=datetime.datetime.utcnow().isoformat()
            ),
            resources=discovered_resources
        )

    def perform_full_scan(self) -> Dict[str, Any]:
        """
        Executes a scan against GCP and returns a dictionary matching the LiveArchitectureSchema.
        """
        schema = self.scan()
        return schema.model_dump()
