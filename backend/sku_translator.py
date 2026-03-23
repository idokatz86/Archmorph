"""
Archmorph SKU Translator — Instance-level cross-cloud translation with performance parity scoring.

Provides SKU-level mapping (e.g. m5.xlarge → Standard_D4s_v5) for compute instances,
database tiers, and storage classes across AWS, GCP, and Azure.
"""

import re
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ═══════════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class InstanceSpec:
    """Hardware specification for a single compute instance type."""
    sku: str
    provider: str           # aws | azure | gcp
    family: str             # General Purpose, Compute Optimized, etc.
    vcpus: int
    ram_gb: float
    network_gbps: float     # approximate max
    storage_type: str       # EBS, Premium SSD, Persistent Disk, etc.
    burstable: bool = False
    gpu: int = 0
    gpu_model: str = ""


@dataclass(frozen=True)
class StorageMapping:
    """Cross-cloud storage tier/class mapping."""
    source_sku: str
    source_provider: str
    azure_sku: str
    category: str           # object | block | archive
    notes: str = ""


@dataclass(frozen=True)
class DatabaseSKUMapping:
    """Cross-cloud database SKU mapping."""
    source_sku: str
    source_provider: str    # aws | gcp
    source_service: str     # RDS, Cloud SQL, etc.
    azure_sku: str
    azure_service: str      # SQL Database, PostgreSQL Flexible Server, etc.
    vcpus: int
    ram_gb: float
    notes: str = ""


@dataclass
class ParityScore:
    """Performance parity breakdown between source and target instance."""
    vcpu_score: float
    ram_score: float
    network_score: float
    storage_score: float
    overall: float
    details: Dict[str, str] = field(default_factory=dict)


@dataclass
class SKUTranslation:
    """Complete translation result for a single SKU."""
    source: InstanceSpec
    target: InstanceSpec
    parity: ParityScore
    alternatives: List[Tuple["InstanceSpec", "ParityScore"]] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
# Instance Type Taxonomy — Top 30 AWS + Top 20 GCP → Azure
# ═══════════════════════════════════════════════════════════════

_AWS_INSTANCES: List[InstanceSpec] = [
    # ─── General Purpose (M-series) ───
    InstanceSpec("m5.large",     "aws", "General Purpose", 2, 8,   10,  "EBS"),
    InstanceSpec("m5.xlarge",    "aws", "General Purpose", 4, 16,  10,  "EBS"),
    InstanceSpec("m5.2xlarge",   "aws", "General Purpose", 8, 32,  10,  "EBS"),
    InstanceSpec("m5.4xlarge",   "aws", "General Purpose", 16, 64, 10,  "EBS"),
    InstanceSpec("m5.8xlarge",   "aws", "General Purpose", 32, 128, 10, "EBS"),
    InstanceSpec("m5.12xlarge",  "aws", "General Purpose", 48, 192, 12, "EBS"),
    InstanceSpec("m6i.large",    "aws", "General Purpose", 2, 8,   12.5, "EBS"),
    InstanceSpec("m6i.xlarge",   "aws", "General Purpose", 4, 16,  12.5, "EBS"),
    InstanceSpec("m6i.2xlarge",  "aws", "General Purpose", 8, 32,  12.5, "EBS"),
    # ─── Compute Optimized (C-series) ───
    InstanceSpec("c5.large",     "aws", "Compute Optimized", 2, 4,  10,  "EBS"),
    InstanceSpec("c5.xlarge",    "aws", "Compute Optimized", 4, 8,  10,  "EBS"),
    InstanceSpec("c5.2xlarge",   "aws", "Compute Optimized", 8, 16, 10,  "EBS"),
    InstanceSpec("c5.4xlarge",   "aws", "Compute Optimized", 16, 32, 10, "EBS"),
    InstanceSpec("c5.9xlarge",   "aws", "Compute Optimized", 36, 72, 12, "EBS"),
    InstanceSpec("c6i.xlarge",   "aws", "Compute Optimized", 4, 8,  12.5, "EBS"),
    InstanceSpec("c6i.2xlarge",  "aws", "Compute Optimized", 8, 16, 12.5, "EBS"),
    # ─── Memory Optimized (R-series) ───
    InstanceSpec("r5.large",     "aws", "Memory Optimized", 2, 16,  10,  "EBS"),
    InstanceSpec("r5.xlarge",    "aws", "Memory Optimized", 4, 32,  10,  "EBS"),
    InstanceSpec("r5.2xlarge",   "aws", "Memory Optimized", 8, 64,  10,  "EBS"),
    InstanceSpec("r5.4xlarge",   "aws", "Memory Optimized", 16, 128, 10, "EBS"),
    InstanceSpec("r6i.large",    "aws", "Memory Optimized", 2, 16,  12.5, "EBS"),
    InstanceSpec("r6i.xlarge",   "aws", "Memory Optimized", 4, 32,  12.5, "EBS"),
    # ─── Burstable (T-series) ───
    InstanceSpec("t3.micro",     "aws", "Burstable", 2, 1,   5, "EBS", burstable=True),
    InstanceSpec("t3.small",     "aws", "Burstable", 2, 2,   5, "EBS", burstable=True),
    InstanceSpec("t3.medium",    "aws", "Burstable", 2, 4,   5, "EBS", burstable=True),
    InstanceSpec("t3.large",     "aws", "Burstable", 2, 8,   5, "EBS", burstable=True),
    InstanceSpec("t3.xlarge",    "aws", "Burstable", 4, 16,  5, "EBS", burstable=True),
    InstanceSpec("t3.2xlarge",   "aws", "Burstable", 8, 32,  5, "EBS", burstable=True),
    # ─── GPU (P/G-series) ───
    InstanceSpec("p3.2xlarge",   "aws", "GPU", 8, 61, 10, "EBS", gpu=1, gpu_model="V100"),
    InstanceSpec("g4dn.xlarge",  "aws", "GPU", 4, 16, 25, "NVMe SSD", gpu=1, gpu_model="T4"),
]

_AZURE_INSTANCES: List[InstanceSpec] = [
    # ─── General Purpose (D-series v5) ───
    InstanceSpec("Standard_D2s_v5",  "azure", "General Purpose", 2, 8,   12.5, "Premium SSD"),
    InstanceSpec("Standard_D4s_v5",  "azure", "General Purpose", 4, 16,  12.5, "Premium SSD"),
    InstanceSpec("Standard_D8s_v5",  "azure", "General Purpose", 8, 32,  12.5, "Premium SSD"),
    InstanceSpec("Standard_D16s_v5", "azure", "General Purpose", 16, 64, 12.5, "Premium SSD"),
    InstanceSpec("Standard_D32s_v5", "azure", "General Purpose", 32, 128, 16,  "Premium SSD"),
    InstanceSpec("Standard_D48s_v5", "azure", "General Purpose", 48, 192, 24,  "Premium SSD"),
    InstanceSpec("Standard_D2ds_v5", "azure", "General Purpose", 2, 8,   12.5, "Temp NVMe SSD"),
    InstanceSpec("Standard_D4ds_v5", "azure", "General Purpose", 4, 16,  12.5, "Temp NVMe SSD"),
    InstanceSpec("Standard_D8ds_v5", "azure", "General Purpose", 8, 32,  12.5, "Temp NVMe SSD"),
    # ─── Compute Optimized (F-series v2) ───
    InstanceSpec("Standard_F2s_v2",  "azure", "Compute Optimized", 2, 4,   5,   "Premium SSD"),
    InstanceSpec("Standard_F4s_v2",  "azure", "Compute Optimized", 4, 8,   7,   "Premium SSD"),
    InstanceSpec("Standard_F8s_v2",  "azure", "Compute Optimized", 8, 16,  12.5, "Premium SSD"),
    InstanceSpec("Standard_F16s_v2", "azure", "Compute Optimized", 16, 32, 12.5, "Premium SSD"),
    InstanceSpec("Standard_F32s_v2", "azure", "Compute Optimized", 32, 64, 16,  "Premium SSD"),
    InstanceSpec("Standard_F48s_v2", "azure", "Compute Optimized", 48, 96, 21,  "Premium SSD"),
    # ─── Memory Optimized (E-series v5) ───
    InstanceSpec("Standard_E2s_v5",  "azure", "Memory Optimized", 2, 16,  12.5, "Premium SSD"),
    InstanceSpec("Standard_E4s_v5",  "azure", "Memory Optimized", 4, 32,  12.5, "Premium SSD"),
    InstanceSpec("Standard_E8s_v5",  "azure", "Memory Optimized", 8, 64,  12.5, "Premium SSD"),
    InstanceSpec("Standard_E16s_v5", "azure", "Memory Optimized", 16, 128, 12.5, "Premium SSD"),
    InstanceSpec("Standard_E2ds_v5", "azure", "Memory Optimized", 2, 16,  12.5, "Temp NVMe SSD"),
    InstanceSpec("Standard_E4ds_v5", "azure", "Memory Optimized", 4, 32,  12.5, "Temp NVMe SSD"),
    # ─── Burstable (B-series) ───
    InstanceSpec("Standard_B1ms",    "azure", "Burstable", 1, 2,   5, "Premium SSD", burstable=True),
    InstanceSpec("Standard_B2ms",    "azure", "Burstable", 2, 8,   5, "Premium SSD", burstable=True),
    InstanceSpec("Standard_B2s",     "azure", "Burstable", 2, 4,   5, "Premium SSD", burstable=True),
    InstanceSpec("Standard_B4ms",    "azure", "Burstable", 4, 16,  5, "Premium SSD", burstable=True),
    InstanceSpec("Standard_B8ms",    "azure", "Burstable", 8, 32,  5, "Premium SSD", burstable=True),
    # ─── GPU (NC/ND-series) ───
    InstanceSpec("Standard_NC6s_v3",  "azure", "GPU", 6, 112, 24, "Premium SSD", gpu=1, gpu_model="V100"),
    InstanceSpec("Standard_NC4as_T4_v3", "azure", "GPU", 4, 28, 8, "Premium SSD", gpu=1, gpu_model="T4"),
]

_GCP_INSTANCES: List[InstanceSpec] = [
    # ─── General Purpose (N2) ───
    InstanceSpec("n2-standard-2",  "gcp", "General Purpose", 2, 8,   10, "Persistent Disk"),
    InstanceSpec("n2-standard-4",  "gcp", "General Purpose", 4, 16,  10, "Persistent Disk"),
    InstanceSpec("n2-standard-8",  "gcp", "General Purpose", 8, 32,  16, "Persistent Disk"),
    InstanceSpec("n2-standard-16", "gcp", "General Purpose", 16, 64, 32, "Persistent Disk"),
    InstanceSpec("n2-standard-32", "gcp", "General Purpose", 32, 128, 32, "Persistent Disk"),
    InstanceSpec("n2-standard-48", "gcp", "General Purpose", 48, 192, 32, "Persistent Disk"),
    # ─── Compute Optimized (C2) ───
    InstanceSpec("c2-standard-4",  "gcp", "Compute Optimized", 4, 16, 10, "Persistent Disk"),
    InstanceSpec("c2-standard-8",  "gcp", "Compute Optimized", 8, 32, 16, "Persistent Disk"),
    InstanceSpec("c2-standard-16", "gcp", "Compute Optimized", 16, 64, 32, "Persistent Disk"),
    InstanceSpec("c2-standard-30", "gcp", "Compute Optimized", 30, 120, 32, "Persistent Disk"),
    # ─── Memory Optimized (M2/N2-highmem) ───
    InstanceSpec("n2-highmem-2",   "gcp", "Memory Optimized", 2, 16,  10, "Persistent Disk"),
    InstanceSpec("n2-highmem-4",   "gcp", "Memory Optimized", 4, 32,  10, "Persistent Disk"),
    InstanceSpec("n2-highmem-8",   "gcp", "Memory Optimized", 8, 64,  16, "Persistent Disk"),
    InstanceSpec("n2-highmem-16",  "gcp", "Memory Optimized", 16, 128, 32, "Persistent Disk"),
    # ─── Burstable (E2) ───
    InstanceSpec("e2-micro",       "gcp", "Burstable", 2, 1,  2, "Persistent Disk", burstable=True),
    InstanceSpec("e2-small",       "gcp", "Burstable", 2, 2,  2, "Persistent Disk", burstable=True),
    InstanceSpec("e2-medium",      "gcp", "Burstable", 2, 4,  2, "Persistent Disk", burstable=True),
    InstanceSpec("e2-standard-2",  "gcp", "Burstable", 2, 8,  4, "Persistent Disk", burstable=True),
    InstanceSpec("e2-standard-4",  "gcp", "Burstable", 4, 16, 8, "Persistent Disk", burstable=True),
    InstanceSpec("e2-standard-8",  "gcp", "Burstable", 8, 32, 8, "Persistent Disk", burstable=True),
]


# ═══════════════════════════════════════════════════════════════
# Direct Mapping Tables (precomputed best matches)
# ═══════════════════════════════════════════════════════════════

# Maps (provider, source_sku) → azure_sku for the primary recommendation
_DIRECT_MAP: Dict[Tuple[str, str], str] = {
    # AWS → Azure  (top 30)
    ("aws", "m5.large"):      "Standard_D2s_v5",
    ("aws", "m5.xlarge"):     "Standard_D4s_v5",
    ("aws", "m5.2xlarge"):    "Standard_D8s_v5",
    ("aws", "m5.4xlarge"):    "Standard_D16s_v5",
    ("aws", "m5.8xlarge"):    "Standard_D32s_v5",
    ("aws", "m5.12xlarge"):   "Standard_D48s_v5",
    ("aws", "m6i.large"):     "Standard_D2s_v5",
    ("aws", "m6i.xlarge"):    "Standard_D4s_v5",
    ("aws", "m6i.2xlarge"):   "Standard_D8s_v5",
    ("aws", "c5.large"):      "Standard_F2s_v2",
    ("aws", "c5.xlarge"):     "Standard_F4s_v2",
    ("aws", "c5.2xlarge"):    "Standard_F8s_v2",
    ("aws", "c5.4xlarge"):    "Standard_F16s_v2",
    ("aws", "c5.9xlarge"):    "Standard_F48s_v2",
    ("aws", "c6i.xlarge"):    "Standard_F4s_v2",
    ("aws", "c6i.2xlarge"):   "Standard_F8s_v2",
    ("aws", "r5.large"):      "Standard_E2s_v5",
    ("aws", "r5.xlarge"):     "Standard_E4s_v5",
    ("aws", "r5.2xlarge"):    "Standard_E8s_v5",
    ("aws", "r5.4xlarge"):    "Standard_E16s_v5",
    ("aws", "r6i.large"):     "Standard_E2s_v5",
    ("aws", "r6i.xlarge"):    "Standard_E4s_v5",
    ("aws", "t3.micro"):      "Standard_B1ms",
    ("aws", "t3.small"):      "Standard_B1ms",
    ("aws", "t3.medium"):     "Standard_B2ms",
    ("aws", "t3.large"):      "Standard_B2ms",
    ("aws", "t3.xlarge"):     "Standard_B4ms",
    ("aws", "t3.2xlarge"):    "Standard_B8ms",
    ("aws", "p3.2xlarge"):    "Standard_NC6s_v3",
    ("aws", "g4dn.xlarge"):   "Standard_NC4as_T4_v3",
    # GCP → Azure  (top 20)
    ("gcp", "n2-standard-2"):  "Standard_D2s_v5",
    ("gcp", "n2-standard-4"):  "Standard_D4s_v5",
    ("gcp", "n2-standard-8"):  "Standard_D8s_v5",
    ("gcp", "n2-standard-16"): "Standard_D16s_v5",
    ("gcp", "n2-standard-32"): "Standard_D32s_v5",
    ("gcp", "n2-standard-48"): "Standard_D48s_v5",
    ("gcp", "c2-standard-4"):  "Standard_F4s_v2",
    ("gcp", "c2-standard-8"):  "Standard_F8s_v2",
    ("gcp", "c2-standard-16"): "Standard_F16s_v2",
    ("gcp", "c2-standard-30"): "Standard_F32s_v2",
    ("gcp", "n2-highmem-2"):   "Standard_E2s_v5",
    ("gcp", "n2-highmem-4"):   "Standard_E4s_v5",
    ("gcp", "n2-highmem-8"):   "Standard_E8s_v5",
    ("gcp", "n2-highmem-16"):  "Standard_E16s_v5",
    ("gcp", "e2-micro"):       "Standard_B1ms",
    ("gcp", "e2-small"):       "Standard_B1ms",
    ("gcp", "e2-medium"):      "Standard_B2ms",
    ("gcp", "e2-standard-2"):  "Standard_B2ms",
    ("gcp", "e2-standard-4"):  "Standard_B4ms",
    ("gcp", "e2-standard-8"):  "Standard_B8ms",
}


# ═══════════════════════════════════════════════════════════════
# Storage Tier Mappings
# ═══════════════════════════════════════════════════════════════

STORAGE_MAPPINGS: List[StorageMapping] = [
    # AWS → Azure (object storage)
    StorageMapping("S3 Standard",         "aws", "Blob Hot",           "object", "General-purpose high-frequency access"),
    StorageMapping("S3 Standard-IA",      "aws", "Blob Cool",          "object", "Infrequent access, lower cost"),
    StorageMapping("S3 One Zone-IA",      "aws", "Blob Cool",          "object", "Single-zone IA — Azure Cool is zone-redundant by default"),
    StorageMapping("S3 Glacier Instant",  "aws", "Blob Cold",          "object", "Millisecond retrieval archive"),
    StorageMapping("S3 Glacier Flexible", "aws", "Blob Archive",       "object", "Flexible retrieval, minutes to hours"),
    StorageMapping("S3 Glacier Deep",     "aws", "Blob Archive",       "object", "Lowest-cost long-term archive"),
    StorageMapping("S3 Intelligent-Tiering", "aws", "Blob Lifecycle Management", "object", "Auto-tiering based on access patterns"),
    # AWS → Azure (block storage)
    StorageMapping("EBS gp3",             "aws", "Premium SSD v2",     "block", "Baseline 3000 IOPS, scalable performance"),
    StorageMapping("EBS gp2",             "aws", "Premium SSD",        "block", "Legacy GP — burstable IOPS"),
    StorageMapping("EBS io1",             "aws", "Ultra Disk",         "block", "Provisioned IOPS, mission-critical"),
    StorageMapping("EBS io2",             "aws", "Ultra Disk",         "block", "High-durability provisioned IOPS"),
    StorageMapping("EBS st1",             "aws", "Standard HDD",       "block", "Throughput-optimized HDD"),
    StorageMapping("EBS sc1",             "aws", "Standard HDD",       "block", "Cold HDD — lowest cost block"),
    # GCP → Azure (object storage)
    StorageMapping("Standard",            "gcp", "Blob Hot",           "object", "Multi-region / regional standard"),
    StorageMapping("Nearline",            "gcp", "Blob Cool",          "object", "30-day minimum, infrequent access"),
    StorageMapping("Coldline",            "gcp", "Blob Cold",          "object", "90-day minimum"),
    StorageMapping("Archive",             "gcp", "Blob Archive",       "object", "365-day minimum, lowest cost"),
    # GCP → Azure (block storage)
    StorageMapping("pd-balanced",         "gcp", "Premium SSD",        "block", "Balanced price/performance"),
    StorageMapping("pd-ssd",             "gcp", "Premium SSD v2",     "block", "SSD persistent disk"),
    StorageMapping("pd-extreme",          "gcp", "Ultra Disk",         "block", "Highest IOPS persistent disk"),
    StorageMapping("pd-standard",         "gcp", "Standard HDD",      "block", "Standard HDD persistent disk"),
]


# ═══════════════════════════════════════════════════════════════
# Database SKU Mappings
# ═══════════════════════════════════════════════════════════════

DATABASE_SKU_MAPPINGS: List[DatabaseSKUMapping] = [
    # AWS RDS → Azure
    DatabaseSKUMapping("db.t3.micro",   "aws", "RDS", "B_Standard_B1ms",      "PostgreSQL Flexible Server", 1, 2,   "Burstable micro tier"),
    DatabaseSKUMapping("db.t3.small",   "aws", "RDS", "B_Standard_B1ms",      "PostgreSQL Flexible Server", 2, 2,   "Burstable small"),
    DatabaseSKUMapping("db.t3.medium",  "aws", "RDS", "B_Standard_B2ms",      "PostgreSQL Flexible Server", 2, 4,   "Burstable medium"),
    DatabaseSKUMapping("db.t3.large",   "aws", "RDS", "B_Standard_B2ms",      "PostgreSQL Flexible Server", 2, 8,   "Burstable large"),
    DatabaseSKUMapping("db.r5.large",   "aws", "RDS", "GP_Standard_D2ds_v4",  "PostgreSQL Flexible Server", 2, 16,  "Memory-optimized → General Purpose Flex"),
    DatabaseSKUMapping("db.r5.xlarge",  "aws", "RDS", "GP_Standard_D4ds_v4",  "PostgreSQL Flexible Server", 4, 32,  "Memory-optimized → General Purpose Flex"),
    DatabaseSKUMapping("db.r5.2xlarge", "aws", "RDS", "GP_Standard_D8ds_v4",  "PostgreSQL Flexible Server", 8, 64,  "Memory-optimized → General Purpose Flex"),
    DatabaseSKUMapping("db.r5.4xlarge", "aws", "RDS", "GP_Standard_D16ds_v4", "PostgreSQL Flexible Server", 16, 128, "Memory-optimized → General Purpose Flex"),
    DatabaseSKUMapping("db.m5.large",   "aws", "RDS", "GP_Standard_D2ds_v4",  "PostgreSQL Flexible Server", 2, 8,   "General Purpose"),
    DatabaseSKUMapping("db.m5.xlarge",  "aws", "RDS", "GP_Standard_D4ds_v4",  "PostgreSQL Flexible Server", 4, 16,  "General Purpose"),
    DatabaseSKUMapping("db.m5.2xlarge", "aws", "RDS", "GP_Standard_D8ds_v4",  "PostgreSQL Flexible Server", 8, 32,  "General Purpose"),
    DatabaseSKUMapping("db.m5.4xlarge", "aws", "RDS", "GP_Standard_D16ds_v4", "PostgreSQL Flexible Server", 16, 64, "General Purpose"),
    # AWS Aurora → Azure SQL Hyperscale
    DatabaseSKUMapping("db.r5.large (Aurora)",  "aws", "Aurora", "HS_Gen5_2",  "SQL Database Hyperscale", 2, 10.4, "Aurora → Azure SQL Hyperscale"),
    DatabaseSKUMapping("db.r5.xlarge (Aurora)", "aws", "Aurora", "HS_Gen5_4",  "SQL Database Hyperscale", 4, 20.8, "Aurora → Azure SQL Hyperscale"),
    DatabaseSKUMapping("db.r5.2xlarge (Aurora)", "aws", "Aurora", "HS_Gen5_8", "SQL Database Hyperscale", 8, 41.6, "Aurora → Azure SQL Hyperscale"),
    # GCP Cloud SQL → Azure
    DatabaseSKUMapping("db-f1-micro",       "gcp", "Cloud SQL", "B_Standard_B1ms",      "PostgreSQL Flexible Server", 1, 0.6,  "Shared-core micro"),
    DatabaseSKUMapping("db-g1-small",       "gcp", "Cloud SQL", "B_Standard_B1ms",      "PostgreSQL Flexible Server", 1, 1.7,  "Shared-core small"),
    DatabaseSKUMapping("db-custom-2-7680",  "gcp", "Cloud SQL", "GP_Standard_D2ds_v4",  "PostgreSQL Flexible Server", 2, 7.5,  "Custom 2 vCPU"),
    DatabaseSKUMapping("db-custom-4-15360", "gcp", "Cloud SQL", "GP_Standard_D4ds_v4",  "PostgreSQL Flexible Server", 4, 15,   "Custom 4 vCPU"),
    DatabaseSKUMapping("db-custom-8-30720", "gcp", "Cloud SQL", "GP_Standard_D8ds_v4",  "PostgreSQL Flexible Server", 8, 30,   "Custom 8 vCPU"),
    DatabaseSKUMapping("db-custom-16-61440","gcp", "Cloud SQL", "GP_Standard_D16ds_v4", "PostgreSQL Flexible Server", 16, 60,  "Custom 16 vCPU"),
]


# ═══════════════════════════════════════════════════════════════
# Family → Azure Series Fallback Map
# ═══════════════════════════════════════════════════════════════

_FAMILY_AZURE_SERIES: Dict[str, str] = {
    "General Purpose":     "D-series v5 (Standard_D*s_v5)",
    "Compute Optimized":   "F-series v2 (Standard_F*s_v2)",
    "Memory Optimized":    "E-series v5 (Standard_E*s_v5)",
    "Burstable":           "B-series (Standard_B*ms)",
    "GPU":                 "NC/ND-series (Standard_NC*)",
    "Storage Optimized":   "L-series v2 (Standard_L*s_v2)",
}


# ═══════════════════════════════════════════════════════════════
# Parity Scoring Engine
# ═══════════════════════════════════════════════════════════════

_STORAGE_COMPAT: Dict[str, List[str]] = {
    "EBS":            ["Premium SSD", "Premium SSD v2", "Temp NVMe SSD"],
    "NVMe SSD":       ["Temp NVMe SSD", "Premium SSD v2"],
    "Persistent Disk": ["Premium SSD", "Premium SSD v2"],
    "Premium SSD":    ["EBS", "Persistent Disk"],
    "Premium SSD v2": ["EBS", "NVMe SSD", "Persistent Disk"],
    "Ultra Disk":     ["NVMe SSD"],
    "Temp NVMe SSD":  ["NVMe SSD", "EBS"],
    "Standard HDD":   ["Persistent Disk"],
}


def _score_vcpu(source: int, target: int) -> Tuple[float, str]:
    diff = abs(source - target)
    if diff == 0:
        return 1.0, f"Exact vCPU match ({source})"
    if diff <= 1:
        return 0.90, f"vCPU: {source} → {target} (±1)"
    if diff <= 2:
        return 0.75, f"vCPU: {source} → {target} (±2)"
    ratio = min(source, target) / max(source, target)
    return round(max(0.4, ratio), 2), f"vCPU: {source} → {target} (ratio {ratio:.0%})"


def _score_ram(source: float, target: float) -> Tuple[float, str]:
    if source == 0 or target == 0:
        return 0.5, "RAM data unavailable"
    ratio = min(source, target) / max(source, target)
    if ratio >= 0.99:
        return 1.0, f"Exact RAM match ({source}GB)"
    if ratio >= 0.80:
        return 0.90, f"RAM: {source}GB → {target}GB (within 20%)"
    if ratio >= 0.50:
        return 0.70, f"RAM: {source}GB → {target}GB (within 50%)"
    return round(max(0.4, ratio), 2), f"RAM: {source}GB → {target}GB (ratio {ratio:.0%})"


def _score_network(source: float, target: float) -> Tuple[float, str]:
    if source == 0 or target == 0:
        return 0.80, "Network bandwidth approximated"
    ratio = min(source, target) / max(source, target)
    if ratio >= 0.80:
        return 1.0, f"Network: {source}Gbps → {target}Gbps (comparable)"
    if ratio >= 0.50:
        return 0.80, f"Network: {source}Gbps → {target}Gbps"
    return round(max(0.5, ratio), 2), f"Network: {source}Gbps → {target}Gbps"


def _score_storage(source: str, target: str) -> Tuple[float, str]:
    if source == target:
        return 1.0, f"Exact storage match ({source})"
    compat = _STORAGE_COMPAT.get(source, [])
    if target in compat:
        return 0.90, f"Storage: {source} → {target} (compatible tier)"
    return 0.70, f"Storage: {source} → {target} (different tier)"


def compute_parity(source: InstanceSpec, target: InstanceSpec) -> ParityScore:
    """Compute weighted performance parity score between two instance specs."""
    vcpu_s, vcpu_d = _score_vcpu(source.vcpus, target.vcpus)
    ram_s, ram_d = _score_ram(source.ram_gb, target.ram_gb)
    net_s, net_d = _score_network(source.network_gbps, target.network_gbps)
    stor_s, stor_d = _score_storage(source.storage_type, target.storage_type)

    # Weighted average: vCPU 35%, RAM 30%, Network 15%, Storage 20%
    overall = round(vcpu_s * 0.35 + ram_s * 0.30 + net_s * 0.15 + stor_s * 0.20, 3)

    return ParityScore(
        vcpu_score=vcpu_s,
        ram_score=ram_s,
        network_score=net_s,
        storage_score=stor_s,
        overall=overall,
        details={
            "vcpu": vcpu_d,
            "ram": ram_d,
            "network": net_d,
            "storage": stor_d,
        },
    )


# ═══════════════════════════════════════════════════════════════
# SKU Translator (Thread-Safe Singleton)
# ═══════════════════════════════════════════════════════════════

class SKUTranslatorEngine:
    """Thread-safe SKU translation engine with best-fit algorithm."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Build lookup indexes once
        self._source_index: Dict[Tuple[str, str], InstanceSpec] = {}
        self._azure_index: Dict[str, InstanceSpec] = {}
        self._family_index: Dict[Tuple[str, str], List[InstanceSpec]] = {}  # (provider, family) → specs

        for spec in _AWS_INSTANCES + _GCP_INSTANCES:
            self._source_index[(spec.provider, spec.sku.lower())] = spec
            key = (spec.provider, spec.family)
            self._family_index.setdefault(key, []).append(spec)

        for spec in _AZURE_INSTANCES:
            self._azure_index[spec.sku.lower()] = spec

        # DB lookup
        self._db_index: Dict[Tuple[str, str], DatabaseSKUMapping] = {}
        for db in DATABASE_SKU_MAPPINGS:
            self._db_index[(db.source_provider, db.source_sku.lower())] = db

        # Storage lookup
        self._storage_index: Dict[Tuple[str, str], StorageMapping] = {}
        for sm in STORAGE_MAPPINGS:
            self._storage_index[(sm.source_provider, sm.source_sku.lower())] = sm

    # ─── Primary Translation ──────────────────────────────────

    def translate(self, source_sku: str, provider: str) -> Optional[SKUTranslation]:
        """
        Translate a source instance type to Azure with parity scoring.

        Returns None if the source SKU is not recognized.
        """
        provider = provider.lower()
        source_key = source_sku.lower()

        source_spec = self._source_index.get((provider, source_key))
        if source_spec is None:
            return None

        azure_sku = _DIRECT_MAP.get((provider, source_key))
        if azure_sku is None:
            return None

        target_spec = self._azure_index.get(azure_sku.lower())
        if target_spec is None:
            return None

        parity = compute_parity(source_spec, target_spec)
        alternatives = self._find_alternatives(source_spec, target_spec.sku)
        return SKUTranslation(
            source=source_spec,
            target=target_spec,
            parity=parity,
            alternatives=alternatives,
        )

    # ─── Best-Fit Algorithm ───────────────────────────────────

    def best_fit(self, text: str, provider: str = "aws") -> Optional[SKUTranslation]:
        """
        Given freeform text (e.g. from a diagram), detect and translate the instance type.

        Strategy:
          1. Exact match against known SKUs
          2. Fuzzy match against instance family prefixes
          3. Category fallback
        """
        provider = provider.lower()
        text_lower = text.lower().strip()

        # 1) Exact match
        for (prov, sku), spec in self._source_index.items():
            if prov == provider and sku in text_lower:
                result = self.translate(spec.sku, provider)
                if result is not None:
                    return result

        # 2) Family prefix match — extract patterns like m5, r5, c5, t3, n2-standard, etc.
        family_patterns = {
            "aws": {
                r"\bm[56]i?\.":   "General Purpose",
                r"\bc[56]i?\.":   "Compute Optimized",
                r"\br[56]i?\.":   "Memory Optimized",
                r"\bt3\.":        "Burstable",
                r"\bp3\.":        "GPU",
                r"\bg4dn\.":      "GPU",
            },
            "gcp": {
                r"\bn2-standard": "General Purpose",
                r"\bc2-standard": "Compute Optimized",
                r"\bn2-highmem":  "Memory Optimized",
                r"\be2-":         "Burstable",
            },
        }
        for pattern, family in family_patterns.get(provider, {}).items():
            if re.search(pattern, text_lower):
                return self._fallback_by_family(provider, family)

        # 3) Category keyword fallback
        category_keywords = {
            "general purpose": "General Purpose",
            "compute optimized": "Compute Optimized",
            "compute-optimized": "Compute Optimized",
            "memory optimized": "Memory Optimized",
            "memory-optimized": "Memory Optimized",
            "burstable": "Burstable",
            "gpu": "GPU",
        }
        for keyword, family in category_keywords.items():
            if keyword in text_lower:
                return self._fallback_by_family(provider, family)

        return None

    def _fallback_by_family(self, provider: str, family: str) -> Optional[SKUTranslation]:
        """Return the first available translation from the given family."""
        specs = self._family_index.get((provider, family), [])
        for spec in specs:
            result = self.translate(spec.sku, provider)
            if result is not None:
                return result
        return None

    def _find_alternatives(self, source: InstanceSpec, primary_sku: str, max_results: int = 3) -> List[Tuple[InstanceSpec, ParityScore]]:
        """Find up to max_results alternative Azure instances ranked by parity."""
        scored: List[Tuple[InstanceSpec, ParityScore]] = []
        for azure_spec in _AZURE_INSTANCES:
            if azure_spec.sku.lower() == primary_sku.lower():
                continue
            parity = compute_parity(source, azure_spec)
            scored.append((azure_spec, parity))

        scored.sort(key=lambda x: x[1].overall, reverse=True)
        return scored[:max_results]

    # ─── Database Translation ─────────────────────────────────

    def translate_database(self, source_sku: str, provider: str) -> Optional[DatabaseSKUMapping]:
        """Translate a database instance SKU to Azure equivalent."""
        return self._db_index.get((provider.lower(), source_sku.lower()))

    # ─── Storage Translation ──────────────────────────────────

    def translate_storage(self, source_sku: str, provider: str) -> Optional[StorageMapping]:
        """Translate a storage tier/class to Azure equivalent."""
        return self._storage_index.get((provider.lower(), source_sku.lower()))

    # ─── Listing Helpers ──────────────────────────────────────

    def list_families(self) -> List[Dict]:
        """Return all instance families with cross-cloud series names."""
        families = {}
        for spec in _AWS_INSTANCES + _GCP_INSTANCES + _AZURE_INSTANCES:
            if spec.family not in families:
                families[spec.family] = {"aws": set(), "gcp": set(), "azure": set()}
            families[spec.family][spec.provider].add(spec.sku)

        result = []
        for name, providers in sorted(families.items()):
            result.append({
                "family": name,
                "azure_series": _FAMILY_AZURE_SERIES.get(name, "Unknown"),
                "aws_types": sorted(providers.get("aws", set())),
                "gcp_types": sorted(providers.get("gcp", set())),
                "azure_types": sorted(providers.get("azure", set())),
            })
        return result

    def list_storage_mappings(self) -> List[Dict]:
        """Return all storage tier mappings."""
        return [
            {
                "source_sku": sm.source_sku,
                "source_provider": sm.source_provider,
                "azure_sku": sm.azure_sku,
                "category": sm.category,
                "notes": sm.notes,
            }
            for sm in STORAGE_MAPPINGS
        ]

    def list_database_mappings(self) -> List[Dict]:
        """Return all database SKU mappings."""
        return [
            {
                "source_sku": db.source_sku,
                "source_provider": db.source_provider,
                "source_service": db.source_service,
                "azure_sku": db.azure_sku,
                "azure_service": db.azure_service,
                "vcpus": db.vcpus,
                "ram_gb": db.ram_gb,
                "notes": db.notes,
            }
            for db in DATABASE_SKU_MAPPINGS
        ]


# Module-level singleton — thread-safe, created once on import
_engine = SKUTranslatorEngine()


def get_sku_translator() -> SKUTranslatorEngine:
    """Return the global SKU translator instance."""
    return _engine
