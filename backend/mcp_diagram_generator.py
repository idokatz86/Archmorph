"""
MCP (Model Context Protocol) integration for advanced diagram generation.
This service replaces the legacy static layout engines for Excalidraw, Draw.io, and Visio.
Instead of calculating manual coordinates, it sends the normalized HLD mapping to 
the respective MCP agent to draft and refine the canvas dynamically.
"""

import os
import json
import logging
import httpx
from typing import Dict, Any

logger = logging.getLogger(__name__)

class DiagramMCPClient:
    def __init__(self, mcp_gateway_url: str = None):
        # The gateway URL to the hosted MCP servers (e.g. DrawIO MCP, Excalidraw MCP)
        self.mcp_gateway_url = mcp_gateway_url or os.getenv("MCP_GATEWAY_URL", "http://localhost:8080/mcp")

    async def generate_diagram(self, format_type: str, analysis_data: Dict[str, Any]) -> str:
        """
        Calls the appropriate MCP server based on format_type ('excalidraw', 'drawio', 'visio').
        Returns the raw file string (JSON for excalidraw/drawio, XML for visio).
        """
        logger.info("Delegating diagram generation to MCP server")
        
        # Build prompt for the MCP agent
        prompt = self._build_prompt(analysis_data)
        
        retry_count = 3
        for attempt in range(retry_count):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        f"{self.mcp_gateway_url}/{format_type}/generate",
                        json={"prompt": prompt, "context": analysis_data}
                    )
                    if response.status_code == 200:
                        try:
                            payload = response.json().get("diagram_payload", "")
                        except ValueError as exc:  # invalid JSON
                            logger.warning(
                                "MCP Gateway returned non-JSON error_type=%s; falling back",
                                type(exc).__name__,
                            )
                            return self._fallback_generation(format_type, analysis_data)
                        if isinstance(payload, str) and payload.strip():
                            return payload
                        logger.warning("MCP Gateway returned empty payload; falling back")
                        return self._fallback_generation(format_type, analysis_data)
                    else:
                        logger.warning(
                            "MCP Gateway returned status=%d; retrying",
                            response.status_code,
                        )
            except httpx.ConnectError as exc:
                logger.warning(
                    "MCP Gateway connection failed error_type=%s; falling back",
                    type(exc).__name__,
                )
                return self._fallback_generation(format_type, analysis_data)
            except httpx.WriteTimeout as exc:
                logger.warning(
                    "MCP Gateway write timeout attempt=%d/%d error_type=%s",
                    attempt + 1,
                    retry_count,
                    type(exc).__name__,
                )
            except httpx.ReadTimeout as exc:
                logger.warning(
                    "MCP Gateway read timeout attempt=%d/%d error_type=%s",
                    attempt + 1,
                    retry_count,
                    type(exc).__name__,
                )
            except httpx.RequestError as exc:
                logger.warning(
                    "MCP Gateway request error attempt=%d/%d error_type=%s",
                    attempt + 1,
                    retry_count,
                    type(exc).__name__,
                )
                
        logger.warning(
            "MCP Gateway failed after attempts=%d; falling back",
            retry_count,
        )
        return self._fallback_generation(format_type, analysis_data)

    def _build_prompt(self, analysis: Dict[str, Any]) -> str:
        title = analysis.get("title", "Azure Architecture Diagram")
        zones = analysis.get("zones", [])
        mappings = analysis.get("mappings", [])

        def _service_name(s: Any) -> str | None:
            """Normalize a service entry from any of several known shapes."""
            if isinstance(s, str):
                return s
            if isinstance(s, dict):
                # Vision analyzer schema (name/short_name), legacy mapping rows
                # (azure_service/source_service), test fixtures (aws/azure/source).
                for key in ("azure_service", "source_service", "azure", "aws", "source", "name", "short_name"):
                    val = s.get(key)
                    if val:
                        return val
            return None

        # Trim to keep the prompt under control on very large analyses.
        zones_summary = [
            {
                "name": z.get("name") if isinstance(z, dict) else None,
                "services": [
                    name for name in (_service_name(s) for s in (z.get("services", []) if isinstance(z, dict) else []))
                    if name
                ],
            }
            for z in zones[:32]
        ]
        mappings_summary = [
            {"from": m.get("source_service") or m.get("source"), "to": m.get("azure_service") or m.get("target"), "category": m.get("category")}
            for m in mappings[:64]
        ]
        return (
            f"Generate a clean, presentation-ready Azure architecture diagram titled '{title}'. "
            f"Zones: {json.dumps(zones_summary)}. "
            f"Service mappings: {json.dumps(mappings_summary)}. "
            "Group services by zone, draw labelled connections only when implied by the mappings, "
            "and use Microsoft Azure brand colours."
        )

    def _fallback_generation(self, format_type: str, analysis_data: Dict[str, Any]) -> str:
        # If MCP is offline, returns an empty/garbage payload, or is not configured,
        # delegate to the deterministic in-process layout engine.
        from diagram_export import generate_diagram as diagram_export_generate
        if format_type in ["excalidraw", "drawio", "visio", "vsdx"]:
            real_format = "vsdx" if format_type == "visio" else format_type
            res = diagram_export_generate(analysis_data, real_format)
            return res.get("content") or ""
        raise ValueError(f"Unsupported MCP format: {format_type}")

# Singleton client
mcp_client = DiagramMCPClient()
