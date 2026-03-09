import subprocess
import json
import time

def run_cmd(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"Command failed: {result.stderr}")
    return result.stdout.strip()

print("1. Assigning identity...")
principal_id = run_cmd(["az", "containerapp", "identity", "assign", "--name", "archmorph-mcp-gateway", "--resource-group", "archmorph-rg-dev", "--system-assigned", "--query", "principalId", "-o", "tsv"])
print(f"Principal ID: {principal_id}")

print("2. Getting OpenAI scope...")
scope = run_cmd(["az", "cognitiveservices", "account", "show", "-n", "archmorph-openai-acm7pd", "-g", "archmorph-rg-dev", "--query", "id", "-o", "tsv"])
print(f"Scope: {scope}")

print("3. Assigning Role...")
try:
    run_cmd(["az", "role", "assignment", "create", "--role", "Cognitive Services OpenAI User", "--assignee-object-id", principal_id, "--assignee-principal-type", "ServicePrincipal", "--scope", scope])
except Exception as e:
    print(f"Assign fail (maybe exists): {e}")

print("4. Getting Endpoint and Deployments...")
endpoint = run_cmd(["az", "cognitiveservices", "account", "show", "-n", "archmorph-openai-acm7pd", "-g", "archmorph-rg-dev", "--query", "properties.endpoint", "-o", "tsv"])
deps_json = run_cmd(["az", "cognitiveservices", "account", "deployment", "list", "-n", "archmorph-openai-acm7pd", "-g", "archmorph-rg-dev", "-o", "json"])
deps = json.loads(deps_json)
deploy_name = deps[0]["name"] if deps else "gpt-4-turbo-preview"

print("5. Getting AZ token to fetch Azure OpenAI keys over Management API directly...")
token = run_cmd(["az", "account", "get-access-token", "--query", "accessToken", "-o", "tsv"])

import urllib.request
req = urllib.request.Request(f"https://management.azure.com{scope}/listKeys?api-version=2023-05-01", method="POST")
req.add_header("Authorization", f"Bearer {token}")
try:
    with urllib.request.urlopen(req) as response:
        keys_data = json.loads(response.read().decode())
        az_op_key = keys_data.get("key1", "")
except Exception as e:
    print(f"Warning: Failed to fetch key directly, we might rely on the managed identity. Exception: {e}")
    az_op_key = ""

print("6. Updating Env Vars on the container app...")
env_vars = [
    f"AZURE_OPENAI_ENDPOINT={endpoint}",
    f"AZURE_OPENAI_DEPLOYMENT={deploy_name}",
    "AZURE_OPENAI_API_VERSION=2024-02-15-preview"
]
if az_op_key:
    env_vars.append(f"AZURE_OPENAI_API_KEY={az_op_key}")

run_cmd(["az", "containerapp", "update", "--name", "archmorph-mcp-gateway", "--resource-group", "archmorph-rg-dev", "--set-env-vars"] + env_vars)
print("ALL DONE")
