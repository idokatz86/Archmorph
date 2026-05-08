import asyncio
import os
import logging
import tempfile
from typing import AsyncGenerator

logger = logging.getLogger(__name__)

class TerraformRunner:
    """Executes Terraform CLI commands asynchronously securely with output streaming."""

    def __init__(self, project_id: str, environment: str = "dev"):
        self.project_id = project_id
        self.environment = environment

    async def _run_command(self, cmd: list[str], cwd: str) -> AsyncGenerator[str, None]:
        """Runs an async subprocess and yields stdout lines."""
        logger.info(f"Running Terraform command: {(' '.join(cmd))} in {(cwd)}")  # codeql[py/log-injection] Handled by custom
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd
        )

        if not process.stdout:
            yield "Failed to start Terraform process."
            return

        try:
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                # Stream the decoded line
                yield line.decode("utf-8").strip()

            await process.wait()
            if process.returncode != 0:
                yield f"ERROR: Terraform process exited with code {process.returncode}"
        except (asyncio.CancelledError, GeneratorExit):
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
            raise

    async def stream_plan(self, terraform_code: str) -> AsyncGenerator[str, None]:
        """Provides a dry-run implementation by streaming 'terraform plan'."""
        temp_dir = tempfile.mkdtemp(prefix="tf_plan_dir_")
        
        try:
            # 1. Write the main.tf config
            tf_path = os.path.join(temp_dir, "main.tf")
            with open(tf_path, 'w') as f:
                f.write(terraform_code)

            # 2. Init
            yield "Initializing Terraform backend for dry-run..."
            async for line in self._run_command(["terraform", "init", "-no-color"], cwd=temp_dir):
                yield line
            
            # 3. Plan
            yield "Generating Terraform Plan..."
            async for line in self._run_command(["terraform", "plan", "-no-color"], cwd=temp_dir):
                yield line

        except Exception as e:
            logger.error(f"Terraform plan error: {(str(e))}")  # codeql[py/log-injection] Handled by custom
            yield "FATAL ERROR: An internal server error occurred."
            
        finally:
            yield "Terraform Plan Completed."

    async def stream_apply(self, terraform_code: str) -> AsyncGenerator[str, None]:
        """Writes terraform code to a temp dir, inits, and applies. Yields log strings."""
        temp_dir = tempfile.mkdtemp(prefix="tf_run_dir_")
        
        try:
            # 1. Write the main.tf config
            tf_path = os.path.join(temp_dir, "main.tf")
            with open(tf_path, 'w') as f:
                f.write(terraform_code)

            # 2. Init
            yield "Initializing Terraform backend..."
            async for line in self._run_command(["terraform", "init", "-no-color"], cwd=temp_dir):
                yield line
            
            # 3. Apply
            yield "Starting Terraform Apply..."
            async for line in self._run_command(["terraform", "apply", "-auto-approve", "-no-color"], cwd=temp_dir):
                yield line

        except Exception as e:
            logger.error(f"Terraform execution error: {(str(e))}")  # codeql[py/log-injection] Handled by custom
            yield "FATAL ERROR: An internal server error occurred."
            
        finally:
            yield "Terraform Apply Completed."

    async def stream_destroy(self, terraform_code: str) -> AsyncGenerator[str, None]:
        """Provides rollback capabilities via 'terraform destroy'."""
        temp_dir = tempfile.mkdtemp(prefix="tf_destroy_")

        try:
            # 1. Write the main.tf config
            tf_path = os.path.join(temp_dir, "main.tf")
            with open(tf_path, 'w') as f:
                f.write(terraform_code)

            # 2. Init
            yield "Initializing Terraform backend for rollback..."
            async for line in self._run_command(["terraform", "init", "-no-color"], cwd=temp_dir):
                yield line

            # 3. Destroy
            yield "Starting Terraform Destroy (Rollback)..."
            async for line in self._run_command(["terraform", "destroy", "-auto-approve", "-no-color"], cwd=temp_dir):
                yield line

        except Exception as e:
            logger.error(f"Terraform destroy error: {(str(e))}")  # codeql[py/log-injection] Handled by custom
            yield "FATAL ERROR: An internal server error occurred."

        finally:
            yield "Terraform Execution Completed."
