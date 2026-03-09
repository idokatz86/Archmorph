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
        
        # Try routing to the real MCP Server Gateway
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    f"{self.mcp_gateway_url}/{format_type}/generate",
                    json={"prompt": prompt, "context": analysis_data}
                )
                if response.status_code == 200:
                    return response.json().get("diagram_payload", "")
        except (httpx.TimeoutException, httpx.RequestError) as e:
            logger.warning(f"MCP Gateway unreachable or timed out for {format_type}: {e}. Falling back to legacy layout engine.")

        # Fallback if Gateway is offline or returns error
        return self._fallback_generation(format_type, analysis_data)

    def _build_prompt(self, analysis: Dict[str, Any]) -> str:
        return f"Generate a highly detailed Azure architecture diagram for the following zones: {json.dumps(analysis.get('zones', []))}."

    def _fallback_generation(self, format_type: str, analysis_data: Dict[str, Any]) -> str:
        # If MCP is offline or not configured, fallback to the legacy layout engine
        from diagram_export import export_drawio_xml, export_excalidraw_json, export_visio_vdX
        if format_type == "excalidraw":
            return export_excalidraw_json(analysis_data)
        elif format_type == "drawio":
            return export_drawio_xml(analysis_data)
        elif format_type == "visio":
            return export_visio_vdX(analysis_data)
        raise ValueError(f"Unsupported MCP format: {format_type}")

# Singleton client
mcp_client = DiagramMCPClient()
