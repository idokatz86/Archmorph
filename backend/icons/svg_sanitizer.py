"""SVG sanitizer — validates and sanitizes SVG content for safety.

Removes:
- <script> elements
- on* event handler attributes
- External references (xlink:href to remote URLs, external images)
- Foreign objects
- Embedded data URIs with non-image MIME types

Enforces:
- Maximum file size
- Valid XML structure
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from io import BytesIO
from typing import Optional

import logging

logger = logging.getLogger(__name__)

MAX_SVG_SIZE = 512 * 1024  # 512 KB per SVG

# Tags that are never allowed
_BLOCKED_TAGS = frozenset({
    "script", "foreignobject", "iframe", "embed", "object", "applet",
    "meta", "link", "import", "use",
})

# Attribute patterns that are never allowed
_BLOCKED_ATTR_RE = re.compile(r"^on[a-z]+$", re.IGNORECASE)

# URL patterns for external references
_EXTERNAL_URL_RE = re.compile(r"^(https?://|//|ftp://)", re.IGNORECASE)

# Dangerous URI schemes (XSS vectors)
_DANGEROUS_SCHEME_RE = re.compile(
    r"^\s*(javascript|vbscript|data\s*:(?!image/))", re.IGNORECASE
)

# Dangerous CSS patterns
_DANGEROUS_CSS_RE = re.compile(
    r"(expression|javascript|vbscript|-moz-binding|url\s*\()", re.IGNORECASE
)

# Allowed data-URI image MIME types
_ALLOWED_DATA_MIMES = frozenset({
    "image/png", "image/jpeg", "image/gif", "image/svg+xml", "image/webp",
})


class SVGSanitizationError(Exception):
    """Raised when SVG validation/sanitization fails."""
    pass


def validate_svg(svg_bytes: bytes) -> str:
    """Validate and sanitize SVG content.

    Parameters
    ----------
    svg_bytes : bytes
        Raw SVG file content.

    Returns
    -------
    str
        Sanitized SVG markup string.

    Raises
    ------
    SVGSanitizationError
        If the SVG is invalid, too large, or contains disallowed content.
    """
    if len(svg_bytes) > MAX_SVG_SIZE:
        raise SVGSanitizationError(
            f"SVG exceeds maximum size ({len(svg_bytes)} > {MAX_SVG_SIZE} bytes)"
        )

    # Parse XML
    try:
        tree = ET.parse(BytesIO(svg_bytes))
    except ET.ParseError as exc:
        raise SVGSanitizationError(f"Invalid SVG XML: {exc}") from exc

    root = tree.getroot()

    # Ensure root is <svg>
    tag_local = _local_tag(root.tag)
    if tag_local != "svg":
        raise SVGSanitizationError(f"Root element must be <svg>, got <{tag_local}>")

    # Walk and sanitize
    _sanitize_element(root)

    # Register default SVG namespace to avoid ns0: prefix
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")

    # Serialize back
    raw = ET.tostring(root, encoding="unicode")

    # Minify: collapse whitespace between tags
    raw = _minify_svg(raw)

    return raw


def _local_tag(tag: str) -> str:
    """Strip namespace from an element tag."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _sanitize_element(el: ET.Element) -> None:
    """Recursively sanitize an XML element tree in-place."""
    # Remove blocked child elements
    to_remove = []
    for child in el:
        child_tag = _local_tag(child.tag).lower()
        if child_tag in _BLOCKED_TAGS:
            logger.warning("Removing blocked element: <%s>", child_tag)
            to_remove.append(child)
        else:
            _sanitize_element(child)

    for child in to_remove:
        el.remove(child)

    # Remove blocked attributes
    attrs_to_remove = []
    for attr_name, attr_val in el.attrib.items():
        local_attr = _local_tag(attr_name).lower()

        # Event handlers
        if _BLOCKED_ATTR_RE.match(local_attr):
            attrs_to_remove.append(attr_name)
            continue

        # External URLs in href/xlink:href/src
        if local_attr in ("href", "src") or attr_name.endswith("}href"):
            if _EXTERNAL_URL_RE.match(attr_val):
                logger.warning("Removing external reference: %s=%s", attr_name, attr_val[:80])
                attrs_to_remove.append(attr_name)
                continue
            # Block javascript:/vbscript: URI schemes (XSS)
            if _DANGEROUS_SCHEME_RE.match(attr_val):
                logger.warning("Removing dangerous URI scheme: %s", attr_val[:80])
                attrs_to_remove.append(attr_name)
                continue
            # Check data URIs for non-image types
            if attr_val.startswith("data:"):
                mime = attr_val.split(";")[0].replace("data:", "")
                if mime not in _ALLOWED_DATA_MIMES:
                    logger.warning("Removing disallowed data URI: %s", mime)
                    attrs_to_remove.append(attr_name)
                    continue

        # Block dangerous CSS in style attributes
        if local_attr == "style" and _DANGEROUS_CSS_RE.search(attr_val):
            logger.warning("Removing dangerous style attribute")
            attrs_to_remove.append(attr_name)
            continue

    for attr in attrs_to_remove:
        del el.attrib[attr]


def _minify_svg(svg: str) -> str:
    """Basic SVG minification — collapse inter-tag whitespace."""
    # Remove XML comments
    svg = re.sub(r"<!--.*?-->", "", svg, flags=re.DOTALL)
    # Collapse whitespace between tags
    svg = re.sub(r">\s+<", "><", svg)
    # Strip leading/trailing whitespace
    svg = svg.strip()
    return svg


def extract_svg_dimensions(svg_str: str) -> tuple[int, int]:
    """Extract width/height from SVG markup. Returns (width, height)."""
    try:
        root = ET.fromstring(svg_str)
    except ET.ParseError:
        return (64, 64)

    def _parse_dim(val: Optional[str]) -> int:
        if not val:
            return 64
        # Strip units (px, pt, em, etc.)
        num = re.sub(r"[^0-9.]", "", val)
        try:
            return max(int(float(num)), 1)
        except (ValueError, TypeError):
            return 64

    w = _parse_dim(root.get("width"))
    h = _parse_dim(root.get("height"))

    # Try viewBox as fallback
    if w == 64 and h == 64:
        vb = root.get("viewBox", "")
        parts = vb.replace(",", " ").split()
        if len(parts) == 4:
            try:
                w = max(int(float(parts[2])), 1)
                h = max(int(float(parts[3])), 1)
            except (ValueError, TypeError):
                pass

    return (w, h)
