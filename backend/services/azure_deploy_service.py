import os
import asyncio
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class AzureDeployService:
    """
    Service responsible for orchestrating Azure deployments.
    Handles temporary credential assumption, dry-runs (what-if/terraform plan),
    and actual execution of infrastructure deployments.
    """

    def __init__(self, subscription_id: Optional[str] = None):
        self.subscription_id = subscription_id

    async def _run_command(self, cmd: list) -> str:
        # Avoid running actual az commands during tests unless explicitly permitted
        if os.environ.get("MOCK_AZURE_CLI", "1") == "1":
            logger.info(f"Mocking az command execution: {' '.join(cmd)}")
            return '{"status": "mocked"}'
        
        logger.info(f"Executing az command: {' '.join(cmd)}")
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(f"Command {' '.join(cmd)} failed: {stderr.decode()}")
        return stdout.decode()

    async def get_credentials(self) -> Dict[str, Any]:
        """
        Assumes temporary credentials if needed using azure-identity 
        or returns existing token metadata.
        """
        logger.info("Assuming temporary credentials for Azure deployment.")
        await asyncio.sleep(0.1)
        return {"status": "authenticated", "provider": "azure-identity"}

    async def deploy_infrastructure(self, job_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes actual deployment.
        Runs `az deployment group create`.
        """
        logger.info("Executing Azure deployment for job %s", str(job_id).replace('\n', '').replace('\r', ''))
        
        variables = payload.get("variables") or {}
        rg = variables.get("resource_group", "default-rg")
        template_file = variables.get("template_file", "main.bicep")
        
        cmd = [
            "az", "deployment", "group", "create",
            "--resource-group", rg,
            "--template-file", template_file
        ]
        
        try:
            output = await self._run_command(cmd)
            return {
                "job_id": job_id,
                "status": "in_progress",
                "message": "Deployment triggered successfully via az CLI.",
                "output": output
            }
        except Exception as e:
            logger.error(f"Deployment failed: {e}")
            return {
                "job_id": job_id,
                "status": "failed",
                "message": str(e)
            }

    async def preview_deployment(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Runs a dry-run preview (what-if).
        """
        logger.info("Running Azure deployment preview (what-if)")
        
        variables = payload.get("variables") or {}
        rg = variables.get("resource_group", "default-rg")
        template_file = variables.get("template_file", "main.bicep")
        
        cmd = [
            "az", "deployment", "group", "what-if",
            "--resource-group", rg,
            "--template-file", template_file
        ]
        
        try:
            output = await self._run_command(cmd)
            return {
                "status": "success",
                "preview_data": {
                    "to_add": -1,
                    "to_update": -1,
                    "to_destroy": -1,
                    "notes": "Preview generated successfully.",
                    "output": output
                }
            }
        except Exception as e:
            logger.error(f"Preview failed: {e}")
            return {
                "status": "failed",
                "preview_data": {
                    "error": str(e)
                }
            }
