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
        logger.info(f"Delegating {format_type} diagram generation to MCP server...")
        
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
                        except ValueError as e:  # invalid JSON
                            logger.warning(
                                f"MCP Gateway returned non-JSON for {format_type}: {e}. Falling back."
                            )
                            return self._fallback_generation(format_type, analysis_data)
                        if isinstance(payload, str) and payload.strip():
                            return payload
                        logger.warning(
                            f"MCP Gateway returned empty payload for {format_type}. Falling back."
                        )
                        return self._fallback_generation(format_type, analysis_data)
                    else:
                        logger.warning(f"MCP Gateway returned status {response.status_code}. Retrying...")
            except httpx.ConnectError as e:
                logger.warning(f"MCP Gateway connection failed for {format_type}: {e}. Falling back to legacy layout engine.")
                return self._fallback_generation(format_type, analysis_data)
            except httpx.WriteTimeout as e:
                logger.warning(f"MCP Gateway write timeout for {format_type}: {e}. Retrying ({attempt+1}/{retry_count})...")
            except httpx.ReadTimeout as e:
                logger.warning(f"MCP Gateway read timeout for {format_type}: {e}. Retrying ({attempt+1}/{retry_count})...")
            except httpx.RequestError as e:
                logger.warning(f"MCP Gateway request error for {format_type}: {e}. Retrying ({attempt+1}/{retry_count})...")
                
        logger.warning(f"MCP Gateway failed or timed out after {retry_count} attempts for {format_type}. Falling back to legacy layout engine.")
        return self._fallback_generation(format_type, analysis_data)

    def _build_prompt(self, analysis: Dict[str, Any]) -> str:
        title = analysis.get("title", "Azure Architecture Diagram")
        zones = analysis.get("zones", [])
        mappings = analysis.get("mappings", [])
        # Trim to keep the prompt under control on very large analyses.
        zones_summary = [
            {"name": z.get("name"), "services": [s.get("azure_service") or s.get("source_service") or s.get("source") for s in z.get("services", [])]}
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
