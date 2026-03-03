"""
HLD Service Layer — domain logic for High-Level Design generation (#355).

This module owns the HLD generation contract, decoupling domain logic
from route handling. Routes call this service; tests can monkeypatch here.

Architecture Decision Record (ADR):
- Option B selected: service layer with thin route adapter
- generate_hld lives here; hld_routes.py delegates to this module
- Legacy compatibility: routers.diagrams re-exports for existing test patches
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def generate_hld(
    analysis: Dict[str, Any],
    cost_estimate: Optional[Dict[str, Any]] = None,
    iac_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Generate a comprehensive High-Level Design document from analysis data.

    This is the canonical entry point for HLD generation. All callers
    (sync routes, async routes, background jobs) should use this function.

    Parameters
    ----------
    analysis : dict
        Analysis result containing mappings, zones, source provider, etc.
    cost_estimate : dict, optional
        Pre-computed cost estimate to embed in HLD.
    iac_params : dict, optional
        IaC parameters (region, SKU strategy) for context.

    Returns
    -------
    dict
        HLD document with sections: executive_summary, architecture_overview,
        services, networking_design, security_design, data_architecture, etc.
    """
    # Import here to avoid circular imports at module level
    from routers.diagrams import generate_hld as _legacy_generate_hld

    return _legacy_generate_hld(
        analysis=analysis,
        cost_estimate=cost_estimate,
        iac_params=iac_params,
    )


def generate_hld_markdown(hld: Dict[str, Any]) -> str:
    """Convert an HLD dict to a Markdown document.

    Parameters
    ----------
    hld : dict
        HLD document as returned by generate_hld().

    Returns
    -------
    str
        Markdown-formatted HLD document.
    """
    from routers.diagrams import generate_hld_markdown as _legacy_md

    return _legacy_md(hld)
