#!/usr/bin/env python3
"""
Archmorph CLI — Command-line interface for the Archmorph Cloud Architecture Translator API.

Thin API client for batch processing, CI/CD integration, and automation.
"""

import json
import logging
import os
import pathlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

import click
import requests
from tabulate import tabulate

# ── Constants ────────────────────────────────────────────────
DEFAULT_API_URL = "http://localhost:8000"
CONFIG_FILENAME = ".archmorphrc"
CONFIG_DIR = pathlib.Path.home() / ".archmorph"
CONFIG_PATH = CONFIG_DIR / "config.json"
VERSION = "1.0.0"
EXPORT_CAPABILITY_HEADER = "X-Export-Capability"
VOLATILE_ANALYSIS_FIELDS = {"export_capability", "export_capability_expires_in"}

logger = logging.getLogger("archmorph")


# ── Config helpers ───────────────────────────────────────────
def _find_config() -> dict:
    """Load config from .archmorphrc (cwd) or ~/.archmorph/config.json."""
    local = pathlib.Path.cwd() / CONFIG_FILENAME
    if local.exists():
        try:
            return json.loads(local.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_config(data: dict) -> None:
    """Persist config to ~/.archmorph/config.json."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(data, indent=2))


# ── HTTP client ──────────────────────────────────────────────
class ArchmorphClient:
    """Thin wrapper around the Archmorph REST API."""

    def __init__(self, base_url: str, api_key: Optional[str] = None, token: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        if self.base_url.endswith("/api"):
            self.base_url = self.base_url[:-4]
        self.export_capability: Optional[str] = None
        self.session = requests.Session()
        self.session.headers["User-Agent"] = f"archmorph-cli/{VERSION}"
        if api_key:
            self.session.headers["X-API-Key"] = api_key
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _capability_headers(self) -> Dict[str, str]:
        if not self.export_capability:
            return {}
        return {EXPORT_CAPABILITY_HEADER: self.export_capability}

    def fork(self) -> "ArchmorphClient":
        worker = ArchmorphClient(self.base_url)
        worker.session.headers.clear()
        worker.session.headers.update(self.session.headers)
        worker.export_capability = self.export_capability
        return worker

    def _remember_export_capability(self, payload: Any, resp: requests.Response) -> None:
        if isinstance(payload, dict) and payload.get("export_capability"):
            self.export_capability = str(payload["export_capability"])
            return
        next_capability = resp.headers.get("X-Export-Capability-Next")
        if next_capability:
            self.export_capability = next_capability

    def _handle_response(self, resp: requests.Response) -> dict:
        """Parse JSON response or raise a readable error."""
        try:
            resp.raise_for_status()
        except requests.HTTPError:
            try:
                body = resp.json()
                detail = body.get("detail") or body.get("message") or resp.text
            except (ValueError, KeyError):
                detail = resp.text
            raise click.ClickException(f"API error ({resp.status_code}): {detail}")
        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        self._remember_export_capability(payload, resp)
        return payload

    # ── Endpoints ────────────────────────────────────────────
    def health(self) -> dict:
        return self._handle_response(self.session.get(self._url("/api/health"), timeout=10))

    def upload_diagram(self, image_path: str, project_id: str = "default") -> dict:
        path = pathlib.Path(image_path)
        if not path.exists():
            raise click.ClickException(f"File not found: {image_path}")
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".svg": "image/svg+xml",
            ".pdf": "application/pdf",
            ".vsdx": "application/vnd.ms-visio.drawing.main+xml",
            ".drawio": "application/xml",
        }
        content_type = mime_map.get(path.suffix.lower(), "application/octet-stream")
        with open(path, "rb") as f:
            files = {"file": (path.name, f, content_type)}
            resp = self.session.post(
                self._url(f"/api/projects/{project_id}/diagrams"),
                files=files,
                timeout=60,
            )
        return self._handle_response(resp)

    def analyze_diagram(self, diagram_id: str) -> dict:
        resp = self.session.post(self._url(f"/api/diagrams/{diagram_id}/analyze"), timeout=120)
        return self._handle_response(resp)

    def restore_session(self, diagram_id: str, analysis: dict) -> dict:
        resp = self.session.post(
            self._url(f"/api/diagrams/{diagram_id}/restore-session"),
            json={"analysis": analysis},
            timeout=30,
        )
        return self._handle_response(resp)

    def generate_iac(self, diagram_id: str, fmt: str = "terraform") -> dict:
        return self.generate_iac_with_options(diagram_id, fmt=fmt, force=False)

    def generate_iac_with_options(self, diagram_id: str, fmt: str = "terraform", force: bool = False) -> dict:
        resp = self.session.post(
            self._url(f"/api/diagrams/{diagram_id}/generate"),
            params={"format": fmt, "force": str(force).lower()},
            timeout=120,
        )
        return self._handle_response(resp)

    def export_landing_zone_svg(self, diagram_id: str, dr_variant: str = "primary") -> dict:
        resp = self.session.post(
            self._url(f"/api/diagrams/{diagram_id}/export-diagram"),
            params={"format": "landing-zone-svg", "dr_variant": dr_variant},
            headers=self._capability_headers(),
            timeout=120,
        )
        return self._handle_response(resp)

    def cost_estimate(self, diagram_id: str) -> dict:
        resp = self.session.get(self._url(f"/api/diagrams/{diagram_id}/cost-estimate"), timeout=30)
        return self._handle_response(resp)

    def generate_hld(self, diagram_id: str) -> dict:
        resp = self.session.post(self._url(f"/api/diagrams/{diagram_id}/generate-hld"), timeout=120)
        return self._handle_response(resp)

    def export_hld(self, diagram_id: str, fmt: str = "docx") -> bytes:
        resp = self.session.post(
            self._url(f"/api/diagrams/{diagram_id}/export-hld"),
            params={"format": fmt},
            headers=self._capability_headers(),
            timeout=60,
        )
        try:
            resp.raise_for_status()
        except requests.HTTPError:
            try:
                detail = resp.json().get("detail", resp.text)
            except ValueError:
                detail = resp.text
            raise click.ClickException(f"API error ({resp.status_code}): {detail}")
        self._remember_export_capability({}, resp)
        return resp.content

    def export_diagram(self, diagram_id: str, fmt: str = "excalidraw") -> dict:
        resp = self.session.post(
            self._url(f"/api/diagrams/{diagram_id}/export-diagram"),
            params={"format": fmt},
            headers=self._capability_headers(),
            timeout=60,
        )
        return self._handle_response(resp)

    def get_drift_baseline(self, baseline_id: str) -> dict:
        resp = self.session.get(self._url(f"/api/drift/baselines/{baseline_id}"), timeout=30)
        return self._handle_response(resp)

    def compare_drift_baseline(self, baseline_id: str, live_state: dict) -> dict:
        resp = self.session.post(
            self._url(f"/api/drift/baselines/{baseline_id}/compare"),
            json={"live_state": live_state},
            timeout=60,
        )
        return self._handle_response(resp)

    def push_iac_pr(
        self,
        repo: str,
        iac_code: str,
        iac_format: str,
        analysis_summary: Optional[dict] = None,
        cost_estimate: Optional[dict] = None,
    ) -> dict:
        ext_map = {"terraform": "tf", "bicep": "bicep"}
        resp = self.session.post(
            self._url("/api/integrations/github/push-pr"),
            json={
                "repo": repo,
                "iac_code": iac_code,
                "iac_format": iac_format,
                "target_path": f"infra/main.{ext_map.get(iac_format, 'txt')}",
                "analysis_summary": analysis_summary or {},
                "cost_estimate": cost_estimate or {},
            },
            timeout=120,
        )
        return self._handle_response(resp)

    def migration_timeline(self, diagram_id: str) -> dict:
        resp = self.session.post(
            self._url(f"/api/diagrams/{diagram_id}/migration-timeline"),
            timeout=120,
        )
        return self._handle_response(resp)

    def export_timeline(self, diagram_id: str, fmt: str = "json") -> requests.Response:
        resp = self.session.get(
            self._url(f"/api/diagrams/{diagram_id}/migration-timeline/export"),
            params={"format": fmt},
            timeout=30,
        )
        try:
            resp.raise_for_status()
        except requests.HTTPError:
            try:
                detail = resp.json().get("detail", resp.text)
            except ValueError:
                detail = resp.text
            raise click.ClickException(f"API error ({resp.status_code}): {detail}")
        return resp

    def download_report(self, diagram_id: str) -> bytes:
        resp = self.session.get(
            self._url(f"/api/diagrams/{diagram_id}/report"),
            params={"format": "pdf"},
            timeout=60,
        )
        try:
            resp.raise_for_status()
        except requests.HTTPError:
            try:
                detail = resp.json().get("detail", resp.text)
            except ValueError:
                detail = resp.text
            raise click.ClickException(f"API error ({resp.status_code}): {detail}")
        return resp.content


# ── Output helpers ───────────────────────────────────────────
def _write_output(data, output_file: Optional[str], fmt: str):
    """Format and write output to stdout or file."""
    if fmt == "json":
        text = json.dumps(data, indent=2)
    elif fmt == "table" and isinstance(data, dict):
        rows = [(k, _truncate(v)) for k, v in data.items()]
        text = tabulate(rows, headers=["Key", "Value"], tablefmt="simple")
    elif fmt == "table" and isinstance(data, list):
        if data and isinstance(data[0], dict):
            text = tabulate(data, headers="keys", tablefmt="simple")
        else:
            text = "\n".join(str(item) for item in data)
    else:
        text = str(data)

    if output_file:
        pathlib.Path(output_file).write_text(text)
        click.echo(click.style(f"Output written to {output_file}", fg="green"))
    else:
        click.echo(text)


def _truncate(value, max_len: int = 120) -> str:
    """Truncate long values for table display."""
    s = str(value)
    return s if len(s) <= max_len else s[:max_len] + "..."


def _write_binary(data: bytes, output_file: str):
    """Write binary content to a file."""
    pathlib.Path(output_file).write_bytes(data)
    size_kb = len(data) / 1024
    click.echo(click.style(f"Saved {output_file} ({size_kb:.1f} KB)", fg="green"))


def _write_json_artifact(path: pathlib.Path, data: Any) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    return path


def _write_text_artifact(path: pathlib.Path, content: str) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _parse_emit_list(raw_emit: str) -> List[str]:
    aliases = {
        "tf": "terraform",
        "terraform": "terraform",
        "bicep": "bicep",
        "alz": "alz-svg",
        "alz-svg": "alz-svg",
        "landing-zone-svg": "alz-svg",
        "cost": "cost",
        "cost-estimate": "cost",
        "all": "all",
    }
    requested: List[str] = []
    for item in raw_emit.split(","):
        key = item.strip().lower()
        if not key:
            continue
        if key not in aliases:
            raise click.ClickException(
                f"Unsupported emit target '{item}'. Use terraform,bicep,alz-svg,cost,all."
            )
        value = aliases[key]
        if value == "all":
            for default_target in ["terraform", "bicep", "alz-svg", "cost"]:
                if default_target not in requested:
                    requested.append(default_target)
        elif value not in requested:
            requested.append(value)
    return requested or ["terraform", "bicep", "alz-svg", "cost"]


def _iac_artifact_path(output_dir: pathlib.Path, iac_format: str) -> pathlib.Path:
    if iac_format == "terraform":
        return output_dir / "terraform" / "main.tf"
    if iac_format == "bicep":
        return output_dir / "bicep" / "main.bicep"
    raise click.ClickException(f"Unsupported IaC output format '{iac_format}'. Use terraform or bicep.")


def _summarize_analysis(analysis: dict, diagram_id: str, target_rg: Optional[str]) -> dict:
    mappings = analysis.get("mappings", []) if isinstance(analysis, dict) else []
    return {
        "diagram_id": diagram_id,
        "target_resource_group": target_rg,
        "source_provider": analysis.get("source_provider"),
        "target_provider": analysis.get("target_provider", "azure"),
        "services_detected": analysis.get("services_detected", len(mappings)),
        "mapping_count": len(mappings) if isinstance(mappings, list) else 0,
    }


def _project_name_from_target_rg(target_rg: str) -> str:
    value = target_rg.strip().lower()
    for prefix in ("rg-", "rg_"):
        if value.startswith(prefix):
            value = value[len(prefix):]
            break
    value = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in value)
    value = value.strip("-_")
    return value or "cloud-migration"


def _apply_run_context(analysis: dict, target_rg: Optional[str]) -> dict:
    if not target_rg:
        return analysis
    enriched = dict(analysis)
    iac_params = dict(enriched.get("iac_parameters") or {})
    iac_params.setdefault("project_name", _project_name_from_target_rg(target_rg))
    iac_params["target_resource_group"] = target_rg
    enriched["iac_parameters"] = iac_params
    enriched["cli_run"] = {
        "target_resource_group": target_rg,
        "project_name": iac_params["project_name"],
    }
    return enriched


def _strip_volatile_analysis_fields(analysis: dict) -> dict:
    return {key: value for key, value in analysis.items() if key not in VOLATILE_ANALYSIS_FIELDS}


def _generate_iac_for_run(client: ArchmorphClient, diagram_id: str, iac_format: str, force: bool) -> dict:
    worker_client = client.fork() if hasattr(client, "fork") else client
    return worker_client.generate_iac_with_options(diagram_id, iac_format, force)


# ── CLI definition ───────────────────────────────────────────
@click.group()
@click.option("--api-url", envvar="ARCHMORPH_API_URL", default=None, help="API base URL.")
@click.option("--api-key", envvar="ARCHMORPH_API_KEY", default=None, help="API key for authentication.")
@click.option("--token", envvar="ARCHMORPH_TOKEN", default=None, help="JWT token for authentication.")
@click.option("--format", "output_format", type=click.Choice(["json", "table"]), default=None, help="Output format.")
@click.option("--output", "output_file", default=None, type=click.Path(), help="Write output to file.")
@click.option("--verbose", is_flag=True, help="Enable debug logging.")
@click.version_option(version=VERSION, prog_name="archmorph")
@click.pass_context
def cli(ctx, api_url, api_key, token, output_format, output_file, verbose):
    """Archmorph CLI — Cloud Architecture Translator for Azure.

    Analyze diagrams, generate IaC, estimate costs, and create HLD documents
    from the command line.
    """
    if verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING)

    cfg = _find_config()
    resolved_url = api_url or cfg.get("api_url") or os.getenv("ARCHMORPH_API_URL") or DEFAULT_API_URL
    resolved_key = api_key or cfg.get("api_key")
    resolved_token = token or cfg.get("token")
    resolved_format = output_format or cfg.get("default_format", "json")

    ctx.ensure_object(dict)
    ctx.obj["client"] = ArchmorphClient(resolved_url, api_key=resolved_key, token=resolved_token)
    ctx.obj["format"] = resolved_format
    ctx.obj["output_file"] = output_file


# ── login ────────────────────────────────────────────────────
@cli.command()
@click.option("--api-key", default=None, help="API key to store.")
@click.option("--token", default=None, help="JWT token to store.")
@click.option("--api-url", default=None, help="API base URL to store.")
def login(api_key, token, api_url):
    """Authenticate and save credentials to config."""
    if not api_key and not token:
        raise click.ClickException("Provide --api-key or --token")
    cfg = _find_config()
    if api_key:
        cfg["api_key"] = api_key
    if token:
        cfg["token"] = token
    if api_url:
        cfg["api_url"] = api_url
    _save_config(cfg)
    click.echo(click.style("Credentials saved to ~/.archmorph/config.json", fg="green"))


# ── status ───────────────────────────────────────────────────
@cli.command()
@click.pass_context
def status(ctx):
    """Check API health and connectivity."""
    client: ArchmorphClient = ctx.obj["client"]
    try:
        data = client.health()
    except requests.ConnectionError:
        raise click.ClickException(f"Cannot connect to {client.base_url}")
    _write_output(data, ctx.obj["output_file"], ctx.obj["format"])


# ── analyze ──────────────────────────────────────────────────
@cli.command()
@click.argument("image_path", type=click.Path(exists=True))
@click.option("--project-id", default="default", help="Project ID for grouping diagrams.")
@click.pass_context
def analyze(ctx, image_path, project_id):
    """Upload and analyze an architecture diagram.

    Uploads the image, then triggers AI-powered analysis to detect cloud services
    and generate Azure migration mappings.
    """
    client: ArchmorphClient = ctx.obj["client"]
    click.echo(click.style("Uploading diagram...", fg="cyan"))
    upload_result = client.upload_diagram(image_path, project_id)
    diagram_id = upload_result["diagram_id"]
    click.echo(click.style(f"Diagram uploaded: {diagram_id}", fg="green"))

    click.echo(click.style("Analyzing architecture...", fg="cyan"))
    analysis = client.analyze_diagram(diagram_id)

    mappings = analysis.get("mappings", [])
    if ctx.obj["format"] == "table" and mappings:
        rows = [
            {
                "Source": m.get("source_service", ""),
                "Azure Service": m.get("azure_service", ""),
                "Category": m.get("category", ""),
                "Confidence": m.get("confidence", ""),
            }
            for m in mappings
        ]
        click.echo(f"\nDiagram ID: {diagram_id}")
        click.echo(f"Services detected: {len(mappings)}\n")
        click.echo(tabulate(rows, headers="keys", tablefmt="simple"))
        if ctx.obj["output_file"]:
            _write_output(analysis, ctx.obj["output_file"], "json")
    else:
        _write_output(analysis, ctx.obj["output_file"], ctx.obj["format"])


# ── run ──────────────────────────────────────────────────────
@cli.command("run")
@click.option(
    "--diagram",
    "diagram_path",
    required=True,
    type=click.Path(exists=True),
    help="Architecture diagram file to upload and analyze.",
)
@click.option("--target-rg", default=None, help="Target Azure resource group name for the run context and IaC project hint.")
@click.option(
    "--emit",
    "emit_targets",
    default="terraform,bicep,alz-svg,cost",
    show_default=True,
    help="Comma-separated outputs: terraform,bicep,alz-svg,cost,all.",
)
@click.option("--out", "output_dir", required=True, type=click.Path(file_okay=False), help="Directory for generated artifacts.")
@click.option("--project-id", default="default", show_default=True, help="Project ID for the uploaded diagram.")
@click.option("--baseline", default=None, help="Optional drift baseline ID to compare the new analysis against.")
@click.option(
    "--push-pr",
    default=None,
    metavar="OWNER/REPO",
    help="Optional GitHub repo to open a PR with the first generated IaC artifact.",
)
@click.option("--force-iac", is_flag=True, help="Pass force=true to IaC generation when architecture blockers exist.")
@click.pass_context
def run_full_spine(
    ctx,
    diagram_path,
    target_rg,
    emit_targets,
    output_dir,
    project_id,
    baseline,
    push_pr,
    force_iac,
):
    """Run the full engineer spine from diagram upload to artifacts on disk.

    Example:
      archmorph run --diagram aws.png --target-rg rg-demo --emit terraform,bicep,alz-svg --out ./infra
    """
    client: ArchmorphClient = ctx.obj["client"]
    requested = _parse_emit_list(emit_targets)
    out_root = pathlib.Path(output_dir)
    artifact_paths: Dict[str, str] = {}
    iac_outputs: Dict[str, str] = {}

    click.echo(click.style("Uploading diagram...", fg="cyan"))
    upload_result = client.upload_diagram(diagram_path, project_id)
    diagram_id = upload_result["diagram_id"]
    click.echo(click.style(f"Diagram uploaded: {diagram_id}", fg="green"))

    click.echo(click.style("Analyzing architecture...", fg="cyan"))
    analysis = client.analyze_diagram(diagram_id)
    analysis = _strip_volatile_analysis_fields(analysis)
    analysis = _apply_run_context(analysis, target_rg)
    if target_rg:
        client.restore_session(diagram_id, analysis)
    artifact_paths["analysis"] = str(_write_json_artifact(out_root / "analysis.json", analysis))

    iac_formats = [target for target in requested if target in {"terraform", "bicep"}]
    if iac_formats:
        click.echo(click.style(f"Generating IaC: {', '.join(iac_formats)}...", fg="cyan"))
        with ThreadPoolExecutor(max_workers=min(len(iac_formats), 4)) as executor:
            futures = {
                executor.submit(_generate_iac_for_run, client, diagram_id, iac_format, force_iac): iac_format
                for iac_format in iac_formats
            }
            for future in as_completed(futures):
                iac_format = futures[future]
                result = future.result()
                code = result.get("code", "")
                if not isinstance(code, str) or not code.strip():
                    raise click.ClickException(f"{iac_format} generation returned empty code")
                artifact_path = _iac_artifact_path(out_root, iac_format)
                _write_text_artifact(artifact_path, code)
                artifact_paths[iac_format] = str(artifact_path)
                iac_outputs[iac_format] = code

    cost_estimate = None
    if "alz-svg" in requested:
        click.echo(click.style("Generating ALZ SVG...", fg="cyan"))
        alz = client.export_landing_zone_svg(diagram_id)
        content = alz.get("content", "")
        if not isinstance(content, str) or "<svg" not in content:
            raise click.ClickException("ALZ SVG generation returned invalid content")
        artifact_paths["alz-svg"] = str(_write_text_artifact(out_root / "alz.svg", content))

    if "cost" in requested:
        click.echo(click.style("Estimating cost...", fg="cyan"))
        cost_estimate = client.cost_estimate(diagram_id)
        artifact_paths["cost"] = str(_write_json_artifact(out_root / "cost-estimate.json", cost_estimate))

    if baseline:
        click.echo(click.style(f"Comparing drift baseline {baseline}...", fg="cyan"))
        client.get_drift_baseline(baseline)
        drift_report = client.compare_drift_baseline(baseline, analysis)
        artifact_paths["drift"] = str(_write_json_artifact(out_root / "drift-report.json", drift_report))

    if push_pr:
        if not iac_outputs:
            raise click.ClickException("--push-pr requires at least one IaC emit target")
        preferred_format = "terraform" if "terraform" in iac_outputs else next(iter(iac_outputs))
        click.echo(click.style(f"Pushing {preferred_format} IaC to GitHub PR...", fg="cyan"))
        pr_result = client.push_iac_pr(
            push_pr,
            iac_outputs[preferred_format],
            preferred_format,
            analysis_summary=_summarize_analysis(analysis, diagram_id, target_rg),
            cost_estimate=cost_estimate,
        )
        artifact_paths["github-pr"] = str(_write_json_artifact(out_root / "github-pr.json", pr_result))

    summary = {
        "diagram_id": diagram_id,
        "target_resource_group": target_rg,
        "emit": requested,
        "artifacts": artifact_paths,
    }
    artifact_paths["run-summary"] = str(_write_json_artifact(out_root / "run-summary.json", summary))

    click.echo(click.style("Full-spine run complete.", fg="green"))
    for name, path in artifact_paths.items():
        click.echo(f"{name}: {path}")


# ── generate ─────────────────────────────────────────────────
@cli.command()
@click.argument("diagram_id")
@click.option(
    "--iac-format", "iac_format",
    type=click.Choice(["terraform", "bicep"]),
    default="terraform",
    help="IaC output format.",
)
@click.pass_context
def generate(ctx, diagram_id, iac_format):
    """Generate Infrastructure as Code from an analyzed diagram.

    Outputs Terraform or Bicep code.
    """
    client: ArchmorphClient = ctx.obj["client"]
    click.echo(click.style(f"Generating {iac_format}...", fg="cyan"))
    result = client.generate_iac(diagram_id, iac_format)

    code = result.get("code", "")
    if ctx.obj["output_file"]:
        ext_map = {"terraform": ".tf", "bicep": ".bicep"}
        out = ctx.obj["output_file"]
        if not pathlib.Path(out).suffix:
            out += ext_map.get(iac_format, ".txt")
        pathlib.Path(out).write_text(code)
        click.echo(click.style(f"IaC written to {out}", fg="green"))
    else:
        click.echo(code)


# ── cost ─────────────────────────────────────────────────────
@cli.command()
@click.argument("diagram_id")
@click.pass_context
def cost(ctx, diagram_id):
    """Get cost estimate for an analyzed architecture."""
    client: ArchmorphClient = ctx.obj["client"]
    data = client.cost_estimate(diagram_id)

    if ctx.obj["format"] == "table":
        services = data.get("services", data.get("line_items", []))
        if isinstance(services, list) and services:
            rows = [
                {
                    "Service": s.get("service", s.get("name", "")),
                    "SKU": s.get("sku", s.get("tier", "")),
                    "Monthly ($)": s.get("monthly_cost", s.get("cost", "")),
                }
                for s in services
            ]
            click.echo(tabulate(rows, headers="keys", tablefmt="simple"))
            total = data.get("total_monthly_cost", data.get("total", ""))
            if total:
                click.echo(f"\nTotal monthly estimate: ${total}")
        else:
            _write_output(data, None, "table")
        if ctx.obj["output_file"]:
            _write_output(data, ctx.obj["output_file"], "json")
    else:
        _write_output(data, ctx.obj["output_file"], ctx.obj["format"])


# ── hld ──────────────────────────────────────────────────────
@cli.command()
@click.argument("diagram_id")
@click.option(
    "--hld-format", "hld_format",
    type=click.Choice(["docx", "pdf", "pptx"]),
    default=None,
    help="Export format. Omit to get raw HLD JSON/markdown.",
)
@click.pass_context
def hld(ctx, diagram_id, hld_format):
    """Generate High-Level Design document.

    Without --hld-format: returns HLD data as JSON.
    With --hld-format: exports the HLD as a downloadable file.
    """
    client: ArchmorphClient = ctx.obj["client"]

    if hld_format:
        click.echo(click.style(f"Generating HLD and exporting as {hld_format}...", fg="cyan"))
        # Ensure HLD exists first
        client.generate_hld(diagram_id)
        content = client.export_hld(diagram_id, hld_format)
        out = ctx.obj["output_file"] or f"archmorph-hld-{diagram_id[:8]}.{hld_format}"
        _write_binary(content, out)
    else:
        click.echo(click.style("Generating HLD...", fg="cyan"))
        data = client.generate_hld(diagram_id)
        _write_output(data, ctx.obj["output_file"], ctx.obj["format"])


# ── export ───────────────────────────────────────────────────
@cli.command("export")
@click.argument("diagram_id")
@click.option(
    "--export-format", "export_format",
    type=click.Choice(["excalidraw", "drawio", "vsdx"]),
    default="excalidraw",
    help="Diagram export format.",
)
@click.pass_context
def export_diagram(ctx, diagram_id, export_format):
    """Export architecture diagram to Excalidraw, Draw.io, or Visio format."""
    client: ArchmorphClient = ctx.obj["client"]
    click.echo(click.style(f"Exporting diagram as {export_format}...", fg="cyan"))
    result = client.export_diagram(diagram_id, export_format)

    content = result.get("content", "")
    filename = result.get("filename", f"archmorph-diagram.{export_format}")
    out = ctx.obj["output_file"] or filename

    pathlib.Path(out).write_text(content if isinstance(content, str) else json.dumps(content))
    click.echo(click.style(f"Diagram exported to {out}", fg="green"))


# ── timeline ─────────────────────────────────────────────────
@cli.command()
@click.argument("diagram_id")
@click.option(
    "--timeline-format", "timeline_format",
    type=click.Choice(["json", "md", "csv"]),
    default="json",
    help="Timeline export format.",
)
@click.pass_context
def timeline(ctx, diagram_id, timeline_format):
    """Generate and export migration timeline.

    Produces a phased migration plan with dependency ordering,
    parallel workstreams, and estimated durations.
    """
    client: ArchmorphClient = ctx.obj["client"]
    click.echo(click.style("Generating migration timeline...", fg="cyan"))

    # Ensure timeline exists
    client.migration_timeline(diagram_id)

    if timeline_format in ("md", "csv"):
        resp = client.export_timeline(diagram_id, timeline_format)
        content = resp.text
        if ctx.obj["output_file"]:
            pathlib.Path(ctx.obj["output_file"]).write_text(content)
            click.echo(click.style(f"Timeline written to {ctx.obj['output_file']}", fg="green"))
        else:
            click.echo(content)
    else:
        resp = client.export_timeline(diagram_id, "json")
        try:
            data = resp.json()
        except ValueError:
            data = resp.text
        _write_output(data, ctx.obj["output_file"], ctx.obj["format"])


# ── report ───────────────────────────────────────────────────
@cli.command()
@click.argument("diagram_id")
@click.pass_context
def report(ctx, diagram_id):
    """Download full analysis report as PDF."""
    client: ArchmorphClient = ctx.obj["client"]
    click.echo(click.style("Generating PDF report...", fg="cyan"))
    content = client.download_report(diagram_id)
    out = ctx.obj["output_file"] or f"archmorph-report-{diagram_id[:8]}.pdf"
    _write_binary(content, out)


# ── Entry point ──────────────────────────────────────────────
def main():
    cli(auto_envvar_prefix="ARCHMORPH")


if __name__ == "__main__":
    main()
