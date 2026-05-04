import json
import logging
import asyncio
from typing import Callable, Dict, Any, List

from scanners.aws_scanner import AWSScanner
from scanners.azure_scanner import AzureScanner
from scanners.gcp_scanner import GCPScanner
from services.credential_manager import get_credentials
from cost_optimizer import analyze_live_finops

logger = logging.getLogger(__name__)

class ToolRegistry:
    """
    Registry for mapping tool schemas to callable functions securely for the AI Agent.
    """
    def __init__(self):
        self._tools: Dict[str, Callable] = {}
        self._schemas: List[Dict[str, Any]] = []
        self._register_default_tools()

    def _register_default_tools(self):
        self.register(
            name="scan_cloud_infrastructure",
            func=self.scan_cloud_infrastructure,
            schema={
                "type": "function",
                "function": {
                    "name": "scan_cloud_infrastructure",
                    "description": "Trigger a live cloud architecture scan for a targeted provider. Reads live state of compute, network, and database resources. Returns raw architecture data and FinOps cost savings results.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "provider": {
                                "type": "string",
                                "enum": ["aws", "azure", "gcp"],
                                "description": "The cloud provider to scan. e.g. aws, azure, or gcp."
                            }
                        },
                        "required": ["provider"]
                    }
                }
            }
        )

    def register(self, name: str, func: Callable, schema: Dict[str, Any]):
        self._tools[name] = func
        self._schemas.append(schema)

    def get_schemas(self) -> List[Dict[str, Any]]:
        return self._schemas
        
    async def execute(self, function_name: str, arguments: str, **context) -> str:
        if function_name not in self._tools:
            return json.dumps({"status": "error", "error": f"Tool {function_name} not found in registry."})
        
        try:
            kwargs = json.loads(arguments)
            # Inject context
            kwargs.update(context)
            
            func = self._tools[function_name]
            
            # Execute synchronously in a thread if it's not async, because scanners are blocking
            if asyncio.iscoroutinefunction(func):
                result = await func(**kwargs)
            else:
                result = await asyncio.to_thread(func, **kwargs)
                
            return json.dumps({"status": "success", "result": result})
        except json.JSONDecodeError:
            return json.dumps({"status": "error", "error": "Invalid JSON arguments."})
        except Exception as e:
            logger.error(f"Error executing tool {function_name}: {e}")
            return json.dumps({"status": "error", "error": str(e)})

    # ---- Domain Action Methods ----

    def scan_cloud_infrastructure(self, provider: str, session_token: str = None) -> Dict[str, Any]:
        """
        Implementation of the cloud scanning logic using the existing scanner classes.
        """
        if not session_token:
            return {"error": "Missing session token. Ensure the user is logged in and context contains session_token."}

        # Get credentials securely
        try:
            creds = get_credentials(session_token, expected_provider=provider)
        except Exception as e:
            return {"error": f"Could not retrieve credentials: {str(e)}"}

        if provider.lower() == "aws":
            scanner = AWSScanner(credentials=creds)
        elif provider.lower() == "azure":
            scanner = AzureScanner(credentials=creds)
        elif provider.lower() == "gcp":
            scanner = GCPScanner(credentials=creds)
        else:
            return {"error": f"Unsupported provider: {provider}"}

        try:
            report = scanner.perform_full_scan()
            finops = analyze_live_finops(report)
            return {
                "scan_data": report,
                "cost_savings": finops,
            }
        except Exception as e:
            return {"error": f"Scan failed: {str(e)}"}


tool_registry = ToolRegistry()
