from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from enum import Enum

class CloudProvider(str, Enum):
    AWS = "AWS"
    AZURE = "Azure"
    GCP = "GCP"

class ResourceType(str, Enum):
    COMPUTE = "Compute"
    STORAGE = "Storage"
    DATABASE = "Database"
    NETWORKING = "Networking"

class CloudResource(BaseModel):
    id: str = Field()
    name: str = Field()
    type: str = Field()
    category: ResourceType = Field()
    region: str = Field()
    state: str = Field()
    tags: Dict[str, str] = Field(default_factory=dict)
    attributes: Dict[str, Any] = Field(default_factory=dict)

class ScanMetadata(BaseModel):
    provider: CloudProvider
    scanned_regions: List[str]
    resource_count: int
    scan_timestamp: str

class LiveArchitectureSchema(BaseModel):
    metadata: ScanMetadata
    resources: List[CloudResource]
