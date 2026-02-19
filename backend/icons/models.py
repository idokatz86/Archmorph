"""Icon system Pydantic models."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Provider(str, Enum):
    azure = "azure"
    aws = "aws"
    gcp = "gcp"
    custom = "custom"


class IconMeta(BaseModel):
    """Canonical metadata for a single icon in the registry."""

    id: str = Field(..., description="Deterministic canonical ID: {provider}_{category}_{name}")
    name: str = Field(..., description="Human-readable display name")
    provider: Provider
    category: str = Field(default="general", description="Icon category (compute, storage, …)")
    tags: list[str] = Field(default_factory=list)
    version: str = Field(default="1.0.0")
    service_id: Optional[str] = Field(default=None, description="Cloud service ID for resolveIcon lookups")
    svg_hash: str = Field(default="", description="SHA-256 hex digest of the canonical SVG bytes")
    width: int = Field(default=64)
    height: int = Field(default=64)


class IconEntry(BaseModel):
    """Full icon record = metadata + raw SVG content."""

    meta: IconMeta
    svg: str = Field(..., description="Sanitized SVG markup")


class IconPackManifest(BaseModel):
    """Metadata JSON bundled with an icon pack ZIP/folder."""

    name: str
    provider: Provider = Provider.custom
    version: str = "1.0.0"
    description: str = ""
    icons: list[IconPackItem] = Field(default_factory=list)


class IconPackItem(BaseModel):
    """One entry inside the manifest."""

    file: str = Field(..., description="Relative path to SVG file inside the pack")
    name: str = Field(default="")
    category: str = Field(default="general")
    tags: list[str] = Field(default_factory=list)
    service_id: Optional[str] = None


# Rebuild to resolve forward refs
IconPackManifest.model_rebuild()
