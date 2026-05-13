import json
import logging
import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Any, Dict
import urllib.request
import urllib.parse

try:
    from utils.logger_utils import sanitize_log
except ImportError:
    def sanitize_log(value):
        return str(value).replace("\n", " ").replace("\r", " ")

app = FastAPI(title="MCP Gateway Proxy")
logger = logging.getLogger(__name__)

class DiagramRequest(BaseModel):
    prompt: str
    context: Dict[str, Any]

def _get_azure_ad_token() -> str:
    """Helper to get AD token for Cognitive Services if using Managed Identity"""
    try:
        from azure.identity import DefaultAzureCredential
        credential = DefaultAzureCredential()
        token_info = credential.get_token("https://cognitiveservices.azure.com/.default")
        return token_info.token
    except Exception as e:
        logger.error(f"Failed to get AD token: {sanitize_log(e)}")
        return ""

def _call_llm_for_mcp_generation(format_type: str, prompt: str, context: Dict[str, Any]) -> str:
    """Uses LLM API to procedurally generate the requested format"""
    azure_openai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    openai_api_key = os.getenv("OPENAI_API_KEY")
    azure_openai_api_key = os.getenv("AZURE_OPENAI_API_KEY", openai_api_key)
    azure_openai_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4-turbo-preview")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")
    
    if not azure_openai_endpoint and not openai_api_key and not azure_openai_api_key:
        return f'{{\n  "error": "No LLM configuration present in Gateway",\n  "format": "{format_type}",\n  "mcp_generated": true\n}}'
        
    format_instructions = ""
    if format_type == "excalidraw":
        format_instructions = (
            "Output strictly valid Excalidraw JSON. Start with '{' and end with '}'. "
            "Do not use Markdown code blocks or wrappers like ```json.\n\n"
            "CRITICAL Excalidraw rules:\n"
            "- roughness: 0 for professional diagrams.\n"
            "- All shape labels: fontSize >= 16. Diagram title: fontSize >= 24. Absolute minimum: 14.\n"
            "- Zone backgrounds: opacity 25-40, strokeStyle 'dashed'. Place zones BEFORE shapes in elements array.\n"
            "- Maximum 4 distinct fill colours per diagram.\n"
            "- Colour palette (fill / stroke):\n"
            "  Frontend: #a5d8ff / #1971c2, Backend: #d0bfff / #7048e8,\n"
            "  Database: #b2f2bb / #2f9e44, Queue: #fff3bf / #fab005,\n"
            "  External: #ffc9c9 / #e03131, Zone bg: #e9ecef / #868e96\n"
            "- Column pitch: 440px (230 box + 210 gap for labeled arrows).\n"
            "- Row pitch: 350px (160 box + 190 gap).\n"
            "- Zone padding: >= 50px on all sides.\n"
            "- Element order: zone backgrounds -> shapes -> arrows -> text labels.\n"
            "- Arrows: use startElementId/endElementId for binding. strokeStyle 'dashed' for async flows."
        )
    elif format_type == "drawio":
        format_instructions = (
            "Output strictly valid Draw.io XML. Start with <mxfile> and end with </mxfile>. "
            "Do not use Markdown code blocks or wrappers like ```xml.\n\n"
            "CRITICAL Draw.io icon rules:\n"
            "- For Azure services, use Azure2 image style: "
            "image;aspect=fixed;html=1;points=[];align=center;image=img/lib/azure2/<category>/<Icon_Name>.svg;\n"
            "- Do NOT use old shape=mxgraph.azure.* style — it does not render in modern draw.io.\n"
            "- Common Azure2 icon paths:\n"
            "  compute/Function_Apps.svg, compute/Virtual_Machine.svg, compute/Kubernetes_Services.svg,\n"
            "  databases/Azure_Cosmos_DB.svg, databases/SQL_Database.svg, databases/Cache_Redis.svg,\n"
            "  networking/Virtual_Networks.svg, networking/Load_Balancers.svg, networking/Front_Doors.svg,\n"
            "  networking/Application_Gateways.svg, networking/Firewalls.svg, networking/Private_Endpoint.svg,\n"
            "  app_services/App_Services.svg, app_services/API_Management_Services.svg,\n"
            "  security/Key_Vaults.svg, management_governance/Monitor.svg,\n"
            "  integration/Service_Bus.svg, integration/Logic_Apps.svg,\n"
            "  storage/Storage_Accounts.svg, identity/Managed_Identities.svg\n\n"
            "Layout guidelines:\n"
            "- Use pageWidth=1900 pageHeight=1500 for complex infrastructure diagrams.\n"
            "- VNets: thick borders (strokeWidth=4). Subnets: dashed borders (strokeWidth=2, dashPattern=8 8).\n"
            "- Position resources inside their subnet containers.\n"
            "- Label traffic flows with protocols/ports. Use edgeStyle=orthogonalEdgeStyle.\n"
            "- Place Monitor/Log Analytics/Sentinel OUTSIDE VNet boundaries.\n"
            "- Emit one mxCell per line (not minified single-line XML)."
        )
    elif format_type == "visio":
        format_instructions = "Output strictly valid Visio VDX/XML schema. Start with <VisioDocument> and end with </VisioDocument>. Do not use Markdown code blocks or wrappers like ```xml."

    system_prompt = f"You are an expert Model Context Protocol server generating diagrams. Only output raw code, no markdown wrapping. {format_instructions}"
    
    if azure_openai_endpoint:
        base_url = azure_openai_endpoint.rstrip("/")
        url = f"{base_url}/openai/deployments/{azure_openai_deployment}/chat/completions?api-version={api_version}"
        headers = {"Content-Type": "application/json"}
        if azure_openai_api_key:
            headers["api-key"] = azure_openai_api_key
        else:
            # Local Auth disabled or no API key, use Managed Identity token
            token = _get_azure_ad_token()
            headers["Authorization"] = f"Bearer {token}"
            
    else:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {openai_api_key}"
        }
        
    data = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"{prompt}\n\nContext:\n{json.dumps(context)}"}
        ],
        "temperature": 0.3
    }
    
    if not azure_openai_endpoint:
        data["model"] = "gpt-4-turbo-preview"
        
    req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers)
    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode())
            content = result["choices"][0]["message"]["content"]
            
            # Robustly sanitize markdown wrappers
            content = content.replace("```json", "").replace("```xml", "").replace("```", "").strip()
            
            # Basic validation
            if format_type == "excalidraw" or format_type == "terraform":
                try:
                    # just verify it builds json/hcl (approx for hcl, maybe json for excalidraw)
                    if format_type == "excalidraw":
                        json.loads(content)
                except json.JSONDecodeError:
                    raise ValueError(f"Generated content for {format_type} is not valid JSON")
                    
            elif format_type in ["drawio", "visio"]:
                if not content.startswith("<") or not content.endswith(">"):
                    raise ValueError(f"Generated text for {format_type} does not look like valid XML")
                    
            return content
    except Exception as e:
        logger.error(f"Error calling LLM: {sanitize_log(e)}")
        raise ValueError("AI Diagram Generation failed")

@app.post("/mcp/{format_type}/generate")
async def generate_mcp_diagram(format_type: str, request: DiagramRequest):
    logger.info(f"Received proxy request for {sanitize_log(format_type)}")  # lgtm[py/log-injection]
    if format_type not in ["excalidraw", "drawio", "visio", "terraform"]:
        raise HTTPException(status_code=400, detail="Unsupported format")
        
    try:
        payload = _call_llm_for_mcp_generation(format_type, request.prompt, request.context)
        return {
            "status": "success",
            "diagram_payload": payload
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
def health():
    return {"status": "ok"}
