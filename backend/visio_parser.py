"""
Archmorph – Visio (.vsdx) Parser
================================
Extracts shapes, connections, and metadata from Microsoft Visio files (.vsdx).
Visio uses the Open Packaging Convention (OPC/ZIP) with XML parts inside.

The parser reads:
  - pages/page*.xml — shape elements with text labels, positions, and connections
  - masters/master*.xml — master shape definitions (stencil library)
  - document.xml — document-level metadata

Extracted shapes are matched against cloud service catalogs to identify
AWS/Azure/GCP services, then fed into the standard analysis pipeline.
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from typing import Any, Dict, List, Optional
from xml.etree.ElementTree import Element  # nosec B405  # nosemgrep: python.lang.security.use-defused-xml.use-defused-xml
import defusedxml.ElementTree as ET  # Secure XML parsing - prevents XXE on uploaded .vsdx files

logger = logging.getLogger(__name__)

# Visio XML namespace map
_NS = {
    "v": "http://schemas.microsoft.com/office/visio/2012/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}

# Common cloud service keywords for classification
_CLOUD_KEYWORDS = {
    # AWS
    "ec2", "s3", "rds", "lambda", "dynamodb", "sqs", "sns", "cloudfront",
    "api gateway", "ecs", "eks", "fargate", "elasticache", "kinesis",
    "route 53", "iam", "cloudwatch", "cognito", "aurora", "redshift",
    "glue", "sagemaker", "step functions", "eventbridge", "elb", "alb",
    # Azure
    "virtual machines", "blob storage", "sql database", "functions",
    "cosmos db", "service bus", "event hub", "aks", "container apps",
    "api management", "cdn", "front door", "key vault", "active directory",
    "app service", "logic apps", "cognitive services", "synapse",
    # GCP
    "compute engine", "cloud storage", "cloud sql", "cloud functions",
    "bigquery", "pub/sub", "gke", "cloud run", "memorystore",
    "cloud cdn", "cloud armor", "cloud spanner", "vertex ai",
    # Generic infra
    "load balancer", "firewall", "vpn", "dns", "cdn", "database",
    "cache", "queue", "storage", "gateway", "proxy", "server",
    "container", "kubernetes", "vm", "virtual machine", "web app",
}


class VisioShape:
    """Represents a single shape extracted from a Visio diagram."""

    def __init__(
        self,
        shape_id: str,
        text: str,
        master_name: str = "",
        x: float = 0.0,
        y: float = 0.0,
        width: float = 0.0,
        height: float = 0.0,
        page: int = 1,
    ):
        self.shape_id = shape_id
        self.text = text.strip()
        self.master_name = master_name
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.page = page

    def to_dict(self) -> Dict[str, Any]:
        return {
            "shape_id": self.shape_id,
            "text": self.text,
            "master_name": self.master_name,
            "position": {"x": self.x, "y": self.y},
            "size": {"width": self.width, "height": self.height},
            "page": self.page,
        }


class VisioConnection:
    """Represents a connection between two shapes."""

    def __init__(self, from_shape: str, to_shape: str, label: str = ""):
        self.from_shape = from_shape
        self.to_shape = to_shape
        self.label = label

    def to_dict(self) -> Dict[str, Any]:
        return {
            "from": self.from_shape,
            "to": self.to_shape,
            "label": self.label,
        }


def is_vsdx(file_bytes: bytes) -> bool:
    """Check if the file is a valid .vsdx (ZIP-based) file."""
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes), "r") as zf:
            names = zf.namelist()
            return any("visio/pages" in n.lower() for n in names)
    except (zipfile.BadZipFile, Exception):
        return False


def parse_vsdx(file_bytes: bytes) -> Dict[str, Any]:
    """
    Parse a .vsdx file and extract shapes, connections, and metadata.

    Args:
        file_bytes: Raw bytes of the .vsdx file.

    Returns:
        Dict with keys: shapes, connections, metadata, pages, cloud_services
    """
    if not is_vsdx(file_bytes):
        raise ValueError("Invalid .vsdx file — not a valid Visio Open XML document")

    shapes: List[VisioShape] = []
    connections: List[VisioConnection] = []
    master_names: Dict[str, str] = {}
    metadata: Dict[str, Any] = {}

    with zipfile.ZipFile(io.BytesIO(file_bytes), "r") as zf:
        names = zf.namelist()

        # 1. Parse master shape definitions
        master_files = [n for n in names if re.match(r"visio/masters/master\d*\.xml", n, re.I)]
        for mf in master_files:
            try:
                tree = ET.parse(zf.open(mf))
                root = tree.getroot()
                for master in root.iter(f"{{{_NS['v']}}}Master"):
                    mid = master.get("ID", "")
                    mname = master.get("Name", "")
                    if mid and mname:
                        master_names[mid] = mname
            except Exception as e:
                logger.warning("Failed to parse master file %s: %s", mf, e)

        # Also try masters/masters.xml (unified master list)
        if "visio/masters/masters.xml" in [n.lower() for n in names]:
            for n in names:
                if n.lower() == "visio/masters/masters.xml":
                    try:
                        tree = ET.parse(zf.open(n))
                        root = tree.getroot()
                        for master in root.iter(f"{{{_NS['v']}}}Master"):
                            mid = master.get("ID", "")
                            mname = master.get("Name", "")
                            if mid and mname:
                                master_names[mid] = mname
                    except Exception as e:
                        logger.warning("Failed to parse masters.xml: %s", e)

        # 2. Parse pages
        page_files = sorted(
            [n for n in names if re.match(r"visio/pages/page\d*\.xml", n, re.I)]
        )

        for page_idx, pf in enumerate(page_files, start=1):
            try:
                tree = ET.parse(zf.open(pf))
                root = tree.getroot()

                # Extract shapes
                for shape_el in root.iter(f"{{{_NS['v']}}}Shape"):
                    sid = shape_el.get("ID", "")
                    master_id = shape_el.get("Master", "")
                    shape_type = shape_el.get("Type", "")

                    # Extract text content
                    text_parts = []
                    for text_el in shape_el.iter(f"{{{_NS['v']}}}Text"):
                        if text_el.text:
                            text_parts.append(text_el.text.strip())
                    text = " ".join(text_parts).strip()

                    # Extract position (XForm)
                    x = y = w = h = 0.0
                    xform = shape_el.find(f"{{{_NS['v']}}}XForm")
                    if xform is not None:
                        pin_x = xform.find(f"{{{_NS['v']}}}PinX")
                        pin_y = xform.find(f"{{{_NS['v']}}}PinY")
                        width_el = xform.find(f"{{{_NS['v']}}}Width")
                        height_el = xform.find(f"{{{_NS['v']}}}Height")
                        x = _safe_float(pin_x)
                        y = _safe_float(pin_y)
                        w = _safe_float(width_el)
                        h = _safe_float(height_el)

                    master_name = master_names.get(master_id, "")

                    # Only include shapes with text or known masters
                    if text or master_name:
                        shapes.append(VisioShape(
                            shape_id=sid,
                            text=text,
                            master_name=master_name,
                            x=x, y=y, width=w, height=h,
                            page=page_idx,
                        ))

                    # Extract connections (Connect elements)
                    if shape_type == "Group":
                        for connect in shape_el.iter(f"{{{_NS['v']}}}Connect"):
                            from_sheet = connect.get("FromSheet", "")
                            to_sheet = connect.get("ToSheet", "")
                            if from_sheet and to_sheet:
                                connections.append(VisioConnection(
                                    from_shape=from_sheet,
                                    to_shape=to_sheet,
                                ))

                # Also check for top-level Connect elements
                connects_el = root.find(f"{{{_NS['v']}}}Connects")
                if connects_el is not None:
                    for connect in connects_el.findall(f"{{{_NS['v']}}}Connect"):
                        from_sheet = connect.get("FromSheet", "")
                        to_sheet = connect.get("ToSheet", "")
                        if from_sheet and to_sheet:
                            connections.append(VisioConnection(
                                from_shape=from_sheet,
                                to_shape=to_sheet,
                            ))

            except Exception as e:
                logger.warning("Failed to parse page %s: %s", pf, e)

        # 3. Parse document metadata
        if "docProps/core.xml" in names:
            try:
                tree = ET.parse(zf.open("docProps/core.xml"))
                root = tree.getroot()
                dc_ns = "http://purl.org/dc/elements/1.1/"
                cp_ns = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
                title = root.find(f"{{{dc_ns}}}title")
                creator = root.find(f"{{{dc_ns}}}creator")
                modified = root.find(f"{{{cp_ns}}}lastModifiedBy")
                metadata["title"] = title.text if title is not None and title.text else ""
                metadata["creator"] = creator.text if creator is not None and creator.text else ""
                metadata["last_modified_by"] = modified.text if modified is not None and modified.text else ""
            except Exception:  # nosec B110 - metadata extraction is best-effort
                pass

    # 4. Classify cloud services from shape text + master names
    cloud_services = _identify_cloud_services(shapes)

    # Deduplicate connections
    seen_conns = set()
    unique_connections = []
    for c in connections:
        key = (c.from_shape, c.to_shape)
        if key not in seen_conns:
            seen_conns.add(key)
            unique_connections.append(c)

    return {
        "shapes": [s.to_dict() for s in shapes],
        "connections": [c.to_dict() for c in unique_connections],
        "metadata": metadata,
        "pages": len(page_files),
        "total_shapes": len(shapes),
        "cloud_services": cloud_services,
    }


def _safe_float(element: Optional[Element]) -> float:
    """Safely extract a float from an XML element."""
    if element is not None and element.text:
        try:
            return float(element.text)
        except ValueError:
            pass
    return 0.0


def _identify_cloud_services(shapes: List[VisioShape]) -> List[Dict[str, Any]]:
    """
    Identify likely cloud services from shape text and master names.
    Returns a list of identified services with confidence scores.
    """
    services = []
    seen = set()

    for shape in shapes:
        combined = f"{shape.text} {shape.master_name}".lower()
        if not combined.strip():
            continue

        for keyword in _CLOUD_KEYWORDS:
            if keyword in combined and keyword not in seen:
                seen.add(keyword)
                # Determine provider from keyword
                provider = _guess_provider(keyword, combined)
                services.append({
                    "name": shape.text or shape.master_name,
                    "keyword_match": keyword,
                    "provider": provider,
                    "confidence": 0.75 if shape.text else 0.50,
                    "shape_id": shape.shape_id,
                    "page": shape.page,
                })

    return services


def _guess_provider(keyword: str, context: str) -> str:
    """Guess the cloud provider from keyword + surrounding text."""
    aws_hints = {"aws", "amazon", "ec2", "s3", "rds", "lambda", "dynamodb", "sqs", "sns",
                 "cloudfront", "route 53", "ecs", "eks", "fargate", "elasticache",
                 "kinesis", "cognito", "aurora", "redshift", "glue", "sagemaker", "elb", "alb"}
    azure_hints = {"azure", "microsoft", "virtual machines", "blob storage", "cosmos",
                   "service bus", "event hub", "aks", "app service", "logic apps",
                   "key vault", "active directory", "front door", "synapse"}
    gcp_hints = {"gcp", "google", "compute engine", "cloud storage", "bigquery",
                 "pub/sub", "gke", "cloud run", "memorystore", "vertex ai",
                 "cloud spanner", "cloud armor"}

    if keyword in aws_hints or any(h in context for h in ("aws", "amazon")):
        return "aws"
    if keyword in azure_hints or any(h in context for h in ("azure", "microsoft")):
        return "azure"
    if keyword in gcp_hints or any(h in context for h in ("gcp", "google cloud")):
        return "gcp"
    return "unknown"
