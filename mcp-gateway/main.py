import json
import logging
import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Any, Dict
import urllib.request
import urllib.parse
from urllib.error import HTTPError, URLError

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
        logger.error(f"Failed to get AD token: {e}")
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
        
    system_prompt = "You are an expert Model Context Protocol server generating diagrams. Only output raw code, no markdown wrapping."
    
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
            return content.strip().strip("`").removeprefix("xml\n").removeprefix("json\n")
    except Exception as e:
        logger.error(f"Error calling LLM: {e}")
        raise ValueError("AI Diagram Generation failed")

@app.post("/mcp/{format_type}/generate")
async def generate_mcp_diagram(format_type: str, request: DiagramRequest):
    logger.info(f"Received proxy request for {format_type}")
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