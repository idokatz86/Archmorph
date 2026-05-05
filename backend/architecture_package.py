"""Customer-facing architecture package exports.

The package renderer keeps Archmorph's architecture analysis as the source of
truth and treats HTML/SVG as presentation targets. It composes the existing
Azure Landing Zone SVG renderer with a small customer-intent profile and
customer-safe talking points.
"""

from __future__ import annotations

import copy
import hashlib
import html
import json
import re
from datetime import datetime, timezone
from typing import Any, Literal

from alz_profile import alz_profile_summary, build_alz_profile
from azure_landing_zone import generate_landing_zone_svg
from azure_landing_zone_schema import infer_dr_mode, infer_regions, infer_tiers_from_mappings
from cost_assumptions import DIRECTIONAL_COST_NOTICE, build_cost_assumptions_artifact
from customer_intent import build_customer_intent_profile
from source_provider import normalize_source_provider
from traceability_map import build_traceability_map, traceability_summary


PackageFormat = Literal["html", "svg"]
DiagramVariant = Literal["primary", "dr"]

def generate_architecture_package(
    analysis: dict[str, Any],
    *,
    format: PackageFormat = "html",
    diagram: DiagramVariant = "primary",
    analysis_id: str | None = None,
) -> dict[str, Any]:
    """Generate the architecture package in HTML or SVG form."""
    if format not in ("html", "svg"):
        raise ValueError("format must be 'html' or 'svg'")
    if diagram not in ("primary", "dr"):
        raise ValueError("diagram must be 'primary' or 'dr'")
    if not isinstance(analysis, dict):
        raise ValueError("analysis must be a dict")

    if format == "svg":
        result = generate_landing_zone_svg(_diagram_analysis(analysis, diagram), dr_variant=diagram)
        filename = result["filename"].replace("landing-zone", "architecture-package")
        cost_filename = f"archmorph-{_safe_filename(analysis)}-cost-assumptions.json"
        manifest = _build_manifest(
            analysis,
            format=format,
            diagram=diagram,
            analysis_id=analysis_id,
            artifact_filenames=[filename, cost_filename],
        )
        cost_assumptions_json = _manifest_json(manifest.get("cost_assumptions", {}))
        return {
            "format": "architecture-package-svg",
            "filename": filename,
            "content": _embed_svg_manifest(result["content"], manifest),
            "manifest": manifest,
            "artifact_contents": {
                cost_filename: cost_assumptions_json,
            },
        }

    primary_svg = _namespace_svg_ids(
        _strip_xml_declaration(generate_landing_zone_svg(_diagram_analysis(analysis, "primary"), dr_variant="primary")["content"]),
        "primary",
    )
    dr_svg = _namespace_svg_ids(
        _strip_xml_declaration(generate_landing_zone_svg(_diagram_analysis(analysis, "dr"), dr_variant="dr")["content"]),
        "dr",
    )
    filename = f"archmorph-{_safe_filename(analysis)}-architecture-package.html"
    target_filename = f"archmorph-{_safe_filename(analysis)}-architecture-package-primary.svg"
    dr_filename = f"archmorph-{_safe_filename(analysis)}-architecture-package-dr.svg"
    cost_filename = f"archmorph-{_safe_filename(analysis)}-cost-assumptions.json"
    manifest = _build_manifest(
        analysis,
        format=format,
        diagram=diagram,
        analysis_id=analysis_id,
        artifact_filenames=[filename, target_filename, dr_filename, cost_filename],
    )
    content = _render_html_package(analysis, primary_svg, dr_svg, manifest)
    cost_assumptions_json = _manifest_json(manifest.get("cost_assumptions", {}))
    return {
        "format": "architecture-package-html",
        "filename": filename,
        "content": content,
        "manifest": manifest,
        "artifact_contents": {
            cost_filename: cost_assumptions_json,
        },
    }


def _render_html_package(
    analysis: dict[str, Any],
    primary_svg: str,
    dr_svg: str,
    manifest: dict[str, Any],
) -> str:
    package_name = _package_name(analysis)
    title = html.escape(f"Archmorph — {package_name} Architecture Package")
    display_name = html.escape(package_name)
    source = html.escape(_source_label(analysis))
    profile = _profile_from_analysis(analysis)
    regions = infer_regions(analysis, dr_variant="primary")
    target_region = html.escape(profile.get("region") or regions[0].get("name", "Selected Azure region"))
    source_file = html.escape(str(analysis.get("source_filename") or analysis.get("filename") or "Customer architecture diagram"))
    intent_rows = "\n".join(
        f"<div><span>{html.escape(label)}</span><strong>{html.escape(value)}</strong></div>"
        for label, value in _profile_rows(profile)
    )
    talking_points = "\n".join(
        f"<div class=\"insight-row\"><div class=\"insight-h\">{html.escape(point[0])}</div><div class=\"insight-b\">{html.escape(point[1])}</div></div>"
        for point in _talking_points(analysis, profile)
    )
    limitations = "\n".join(
        f"<div class=\"insight-row\"><div class=\"insight-h\">{html.escape(item[0])}</div><div class=\"insight-b\">{html.escape(item[1])}</div></div>"
        for item in _limitations(analysis, profile)
    )
    dr_readiness = manifest.get("dr_readiness")
    if not isinstance(dr_readiness, dict):
        dr_readiness = _build_dr_readiness_rubric(analysis, profile)
    dr_score = html.escape(str(dr_readiness["score"]))
    dr_rating = html.escape(str(dr_readiness["rating"]))
    dr_summary = html.escape(str(dr_readiness["summary"]))
    dr_rows = "\n".join(
        _render_dr_rubric_row(item)
        for item in dr_readiness["dimensions"]
    )
    dr_limitations = "\n".join(
        f"<li>{html.escape(item)}</li>"
        for item in dr_readiness["limitations"]
    )
    tier_summary = "\n".join(
        f"<li><strong>{html.escape(tier.title())}</strong><span>{html.escape(', '.join(names) or 'Review required')}</span></li>"
        for tier, names in _tier_summary(analysis)
    )
    cost_panel = _render_cost_assumptions_panel(manifest.get("cost_assumptions", {}))

    manifest_json = _manifest_json(manifest)
    cost_assumptions_json = _manifest_json(manifest.get("cost_assumptions", {}))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>
    :root {{ color-scheme: light; --ink:#111827; --muted:#526178; --line:#d9e0ea; --azure:#0078d4; --brand:#0078d4; --brand-2:#5c2d91; --bg:#f6f8fb; --card:#ffffff; --soft:#edf4ff; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); color: var(--ink); font-family: "Segoe UI", system-ui, -apple-system, BlinkMacSystemFont, sans-serif; }}
    .shell {{ max-width: 1440px; margin: 0 auto; padding: 18px 24px 32px; }}
    header {{ display: flex; justify-content: space-between; gap: 18px; align-items: flex-start; padding: 18px 20px; background: #fff; border: 1px solid var(--line); border-radius: 8px; box-shadow: 0 10px 30px rgba(17, 24, 39, 0.06); }}
    .brand {{ display: flex; align-items: center; gap: 12px; }}
    .mark {{ width: 42px; height: 42px; border-radius: 8px; background: linear-gradient(135deg, var(--brand), var(--brand-2)); color: #fff; display: grid; place-items: center; font-weight: 800; }}
    h1 {{ margin: 0; font-size: 24px; line-height: 1.2; letter-spacing: 0; }}
    header p {{ margin: 5px 0 0; color: var(--muted); font-size: 13px; }}
    .meta-pills {{ display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; max-width: 540px; }}
    .brand-pill {{ display: inline-flex; align-items: center; min-height: 28px; border-radius: 8px; padding: 5px 9px; background: var(--soft); color: #155f9f; font-size: 12px; font-weight: 700; }}
    .story {{ display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 14px 0; padding: 12px 14px; background: #fff; border: 1px solid var(--line); border-radius: 8px; color: var(--muted); font-size: 13px; }}
    .story strong {{ color: var(--ink); }}
    nav {{ display: grid; grid-template-columns: repeat(5, minmax(160px, 1fr)); gap: 10px; margin-bottom: 14px; position: sticky; top: 0; z-index: 2; background: rgba(246, 248, 251, 0.94); padding: 8px 0; backdrop-filter: blur(8px); }}
    button.tab {{ border: 1px solid var(--line); background: #fff; color: var(--ink); border-radius: 8px; padding: 11px 12px; font: inherit; font-size: 13px; font-weight: 750; cursor: pointer; text-align: left; box-shadow: 0 4px 14px rgba(17, 24, 39, 0.04); }}
    button.tab span {{ display: block; margin-top: 4px; color: var(--muted); font-size: 11px; font-weight: 650; }}
    button.tab[aria-selected="true"] {{ border-color: #b8d8f5; background: #edf4ff; color: #074f87; }}
    main {{ padding: 0; }}
    section.panel {{ display: none; }}
    section.panel.active {{ display: block; }}
    .diagram {{ overflow: auto; background: #fff; border: 1px solid var(--line); border-radius: 8px; padding: 12px; box-shadow: 0 12px 34px rgba(17, 24, 39, 0.07); }}
    .diagram svg {{ width: 100%; min-width: 1100px; height: auto; display: block; }}
    .grid {{ display: grid; grid-template-columns: minmax(280px, 0.8fr) minmax(420px, 1.2fr); gap: 16px; align-items: start; }}
    .block {{ background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 16px; box-shadow: 0 8px 24px rgba(17, 24, 39, 0.05); }}
    h2 {{ margin: 0 0 12px; font-size: 16px; }}
    ul {{ margin: 0; padding-left: 20px; }}
    li {{ margin: 8px 0; color: #27344a; line-height: 1.45; }}
    .intent {{ display: grid; gap: 8px; }}
    .intent div {{ display: grid; grid-template-columns: 150px 1fr; gap: 12px; border-bottom: 1px solid #edf1f6; padding-bottom: 8px; }}
    .intent div:last-child {{ border-bottom: 0; padding-bottom: 0; }}
    .intent span {{ color: var(--muted); font-size: 12px; }}
    .intent strong {{ font-size: 13px; font-weight: 600; overflow-wrap: anywhere; }}
    .tiers {{ list-style: none; padding: 0; }}
    .tiers li {{ display: grid; grid-template-columns: 130px 1fr; gap: 12px; margin: 0; padding: 9px 0; border-bottom: 1px solid #edf1f6; }}
    .tiers li:last-child {{ border-bottom: 0; }}
    .tiers span {{ color: var(--muted); overflow-wrap: anywhere; }}
    .dr-layout {{ display: grid; grid-template-columns: minmax(0, 1.45fr) minmax(360px, 0.55fr); gap: 16px; align-items: start; }}
    .readiness-head {{ display: grid; grid-template-columns: auto 1fr; gap: 12px; align-items: center; margin-bottom: 12px; }}
    .readiness-score {{ width: 72px; height: 72px; border: 1px solid #b8d8f5; border-radius: 8px; background: #edf4ff; color: #074f87; display: grid; place-items: center; font-size: 22px; font-weight: 800; }}
    .readiness-head h2 {{ margin-bottom: 4px; }}
    .readiness-head p {{ margin: 0; color: var(--muted); font-size: 12px; line-height: 1.45; }}
    .rubric {{ display: grid; gap: 8px; }}
    .rubric-row {{ border: 1px solid #e7edf5; border-radius: 8px; padding: 10px; background: #fbfdff; }}
    .rubric-top {{ display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 5px; }}
    .rubric-name {{ font-size: 13px; font-weight: 800; color: var(--ink); }}
    .rubric-status {{ border-radius: 8px; padding: 3px 7px; font-size: 11px; font-weight: 800; color: #fff; white-space: nowrap; }}
    .rubric-status.ready {{ background: #0f766e; }}
    .rubric-status.partial {{ background: #b45309; }}
    .rubric-status.gap {{ background: #b91c1c; }}
    .rubric-note {{ font-size: 12px; line-height: 1.45; color: #314158; }}
    .dr-limits {{ margin-top: 12px; padding-left: 18px; }}
    .dr-limits li {{ font-size: 12px; }}
        .insight-list {{ display: grid; gap: 10px; }}
        .insight-row {{ border: 1px solid #e7edf5; border-radius: 8px; padding: 12px; background: #fbfdff; }}
        .insight-h {{ font-size: 13px; font-weight: 800; color: var(--ink); margin-bottom: 5px; }}
        .insight-b {{ font-size: 13px; line-height: 1.5; color: #314158; }}
        .cost-actions {{ display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 12px; }}
        .download-link {{ display: inline-flex; align-items: center; min-height: 34px; border: 1px solid #b8d8f5; border-radius: 8px; padding: 7px 10px; background: #edf4ff; color: #074f87; font-size: 12px; font-weight: 800; text-decoration: none; }}
        footer {{ margin-top: 16px; color: var(--muted); font-size: 12px; }}
        @media (max-width: 900px) {{ .shell {{ padding: 12px; }} header {{ flex-direction: column; }} .meta-pills {{ justify-content: flex-start; }} .grid {{ grid-template-columns: 1fr; }} .dr-layout {{ grid-template-columns: 1fr; }} nav {{ grid-template-columns: 1fr; position: static; }} }}
  </style>
</head>
<body>
    <div class="shell">
    <header>
        <div class="brand"><div class="mark">A↻</div><div><h1>{title}</h1><p>Cross-cloud architecture translation and Azure hardening package</p></div></div>
        <div class="meta-pills"><span class="brand-pill">Customer / workload: {display_name}</span><span class="brand-pill">Source: {source}</span><span class="brand-pill">Target: Azure</span><span class="brand-pill">Region: {target_region}</span></div>
    </header>
    <div class="story"><strong>{source_file}</strong><span>→</span><span>Archmorph produced five review outputs:</span><span class="brand-pill">A · Target</span><span class="brand-pill">B · DR</span><span class="brand-pill">C · Talking Points</span><span class="brand-pill">D · Limitations</span><span class="brand-pill">E · Cost Assumptions JSON</span></div>
    <nav aria-label="Architecture package sections">
        <button class="tab" type="button" data-tab="as-is" aria-selected="true">A — Target Azure Topology<span>customer-ready package</span></button>
        <button class="tab" type="button" data-tab="dr" aria-selected="false">B — DR Topology<span>resilience review</span></button>
        <button class="tab" type="button" data-tab="talking" aria-selected="false">C — Talking Points<span>customer-facing narrative</span></button>
        <button class="tab" type="button" data-tab="limits" aria-selected="false">D — Services Limitations<span>technical gotchas</span></button>
        <button class="tab" type="button" data-tab="cost" aria-selected="false">E — Cost Assumptions<span>reviewable JSON artifact</span></button>
    </nav>
    <main>
    <section id="as-is" class="panel active"><div class="diagram">{primary_svg}</div></section>
    <section id="dr" class="panel"><div class="dr-layout"><div class="diagram">{dr_svg}</div><aside class="block"><div class="readiness-head"><div class="readiness-score">{dr_score}</div><div><h2>DR Readiness Rubric</h2><p><strong>{dr_rating}</strong> · {dr_summary}</p></div></div><div class="rubric">{dr_rows}</div><ul class="dr-limits">{dr_limitations}</ul></aside></div></section>
        <section id="talking" class="panel"><div class="grid"><div class="block"><h2>Customer Intent</h2><div class="intent">{intent_rows}</div></div><div class="block"><h2>Recommended Narrative</h2><div class="insight-list">{talking_points}</div></div></div></section>
        <section id="limits" class="panel"><div class="grid"><div class="block"><h2>Service Tiers</h2><ul class="tiers">{tier_summary}</ul></div><div class="block"><h2>Assumptions And Constraints</h2><div class="insight-list">{limitations}</div></div></div></section>
          <section id="cost" class="panel">{cost_panel}</section>
  </main>
    <footer>Archmorph · {display_name} · {source} → Azure · generated from the customer-uploaded architecture diagram.</footer>
    </div>
  <script>
        window.__ARCHMORPH_ARTIFACT_MANIFEST__ = {manifest_json};
    document.querySelectorAll('button.tab').forEach((button) => {{
      button.addEventListener('click', () => {{
        document.querySelectorAll('button.tab').forEach((tab) => tab.setAttribute('aria-selected', 'false'));
        document.querySelectorAll('section.panel').forEach((panel) => panel.classList.remove('active'));
        button.setAttribute('aria-selected', 'true');
        document.getElementById(button.dataset.tab).classList.add('active');
      }});
    }});
        const costDownload = document.getElementById('download-cost-assumptions');
        if (costDownload) {{
            costDownload.href = 'data:application/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(window.__ARCHMORPH_ARTIFACT_MANIFEST__.cost_assumptions || {{}}, null, 2));
        }}
  </script>
  <script type="application/json" id="archmorph-artifact-manifest">{html.escape(manifest_json)}</script>
    <script type="application/json" id="archmorph-cost-assumptions">{html.escape(cost_assumptions_json)}</script>
</body>
</html>"""


def _render_cost_assumptions_panel(cost_assumptions: Any) -> str:
    if not isinstance(cost_assumptions, dict):
        cost_assumptions = {}
    total = cost_assumptions.get("total_monthly_estimate") if isinstance(cost_assumptions.get("total_monthly_estimate"), dict) else {}
    services = [service for service in cost_assumptions.get("services", []) if isinstance(service, dict)]
    rows = "\n".join(
        "<div class=\"insight-row\">"
        f"<div class=\"insight-h\">{html.escape(str(service.get('service') or 'Unknown service'))}</div>"
        f"<div class=\"insight-b\">{html.escape(str(service.get('quantity_assumption') or 'Quantity not specified.'))} "
        f"{html.escape(str(service.get('reservation_assumption') or 'Reservation not specified.'))} "
        f"Monthly range: ${float(service.get('monthly_low') or 0):,.2f} to ${float(service.get('monthly_high') or 0):,.2f}. "
        f"Source: {html.escape(', '.join(str(item) for item in service.get('source_services', []) if item) or str(service.get('source_service') or 'Not mapped'))}.</div>"
        "</div>"
        for service in services[:12]
    )
    if not rows:
        rows = "<div class=\"insight-row\"><div class=\"insight-b\">No priced services were generated for this package.</div></div>"
    return (
        "<div class=\"block\">"
        "<div class=\"cost-actions\"><h2>Cost Assumptions</h2>"
        "<a class=\"download-link\" id=\"download-cost-assumptions\" download=\"archmorph-cost-assumptions.json\" href=\"#\">Download JSON</a></div>"
        f"<p class=\"insight-b\">{html.escape(str(cost_assumptions.get('directional_notice') or DIRECTIONAL_COST_NOTICE))}</p>"
        f"<div class=\"intent\"><div><span>Region</span><strong>{html.escape(str(cost_assumptions.get('region') or 'Not generated'))}</strong></div>"
        f"<div><span>SKU Strategy</span><strong>{html.escape(str(cost_assumptions.get('sku_strategy') or 'Not generated'))}</strong></div>"
        f"<div><span>Monthly Range</span><strong>${float(total.get('low') or 0):,.2f} to ${float(total.get('high') or 0):,.2f}</strong></div></div>"
        f"<div class=\"insight-list\" style=\"margin-top:12px\">{rows}</div>"
        "</div>"
    )


def _build_manifest(
    analysis: dict[str, Any],
    *,
    format: PackageFormat,
    diagram: DiagramVariant,
    analysis_id: str | None,
    artifact_filenames: list[str],
) -> dict[str, Any]:
    profile = _profile_from_analysis(analysis)
    limitations = _limitations(analysis, profile)
    dr_readiness = _build_dr_readiness_rubric(analysis, profile)
    cost_assumptions = build_cost_assumptions_artifact(analysis, analysis_id=analysis_id)
    source_provider = _source_label(analysis)
    raw_warnings = [str(w) for w in analysis.get("warnings", []) if w]
    unsupported = analysis.get("unsupported_assumptions") or analysis.get("unsupported") or []
    if not isinstance(unsupported, list):
        unsupported = [unsupported]

    manifest = {
        "schema_version": "architecture-package-manifest/v1",
        "analysis_id": str(analysis_id or analysis.get("analysis_id") or analysis.get("diagram_id") or "unknown"),
        "source_provider": source_provider,
        "target_provider": "Azure",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "export": {"format": format, "diagram": diagram},
        "renderer": {"name": "architecture_package", "version": "1"},
        "customer_intent_profile_hash": hashlib.sha256(
            json.dumps(profile, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "artifact_filenames": artifact_filenames,
        "artifacts": [
            {"filename": name, "role": role, "format": artifact_format}
            for name, role, artifact_format in _manifest_artifacts(artifact_filenames, format)
        ],
        "mapping_references": _mapping_references(analysis),
        "alz_profile": build_alz_profile(analysis),
        "traceability_map": build_traceability_map(analysis),
        "dr_readiness": dr_readiness,
        "cost_assumptions": cost_assumptions,
        "warnings": raw_warnings[:10],
        "limitations": [
            {"title": title, "detail": detail}
            for title, detail in limitations
        ],
        "unsupported_assumptions": [str(item) for item in unsupported if item][:10],
    }
    return _sanitize_manifest(manifest)


def _manifest_artifacts(
    filenames: list[str],
    format: PackageFormat,
) -> list[tuple[str, str, str]]:
    artifacts: list[tuple[str, str, str]] = []
    if format == "svg":
        artifacts.append((filenames[0], "selected-topology", "svg"))
        remaining = filenames[1:]
    else:
        roles = ["architecture-package-html", "target-topology-svg", "dr-topology-svg"]
        formats = ["html", "svg", "svg"]
        artifacts.extend(zip(filenames[:3], roles, formats))
        remaining = filenames[3:]
    for filename in remaining:
        if filename.endswith("-cost-assumptions.json"):
            artifacts.append((filename, "cost-assumptions", "json"))
    return artifacts


def _mapping_references(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    for mapping in analysis.get("mappings", []):
        if not isinstance(mapping, dict):
            continue
        source = mapping.get("source_service") or mapping.get("source") or mapping.get("aws_service") or mapping.get("gcp_service")
        target = mapping.get("azure_service") or mapping.get("target")
        if not source or not target:
            continue
        ref: dict[str, Any] = {
            "source_service": str(source),
            "azure_service": str(target),
        }
        if mapping.get("source_provider"):
            ref["source_provider"] = str(mapping["source_provider"])
        if mapping.get("category"):
            ref["category"] = str(mapping["category"])
        if mapping.get("confidence") is not None:
            ref["confidence"] = mapping["confidence"]
        references.append(ref)
    return references[:200]


def _manifest_json(manifest: dict[str, Any]) -> str:
    return (
        json.dumps(manifest, sort_keys=True, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def _embed_svg_manifest(svg: str, manifest: dict[str, Any]) -> str:
    manifest_json = _manifest_json(manifest)
    metadata = (
        '<metadata id="archmorph-artifact-manifest" '
        'type="application/json">'
        f'{html.escape(manifest_json)}'
        '</metadata>'
    )
    return re.sub(r"(<svg\b[^>]*>)", lambda match: f"{match.group(1)}{metadata}", svg, count=1)


def _sanitize_manifest(value: Any, key: str = "") -> Any:
    secret_words = ("secret", "password", "token", "credential", "connection_string", "apikey", "api_key")
    if any(word in key.lower() for word in secret_words):
        return "[redacted]"
    if isinstance(value, dict):
        return {str(k): _sanitize_manifest(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_manifest(item, key) for item in value]
    if isinstance(value, str):
        lower = value.lower()
        if any(f"{word}=" in lower or f"{word}:" in lower for word in secret_words):
            return "[redacted]"
    return value


def _profile_from_analysis(analysis: dict[str, Any]) -> dict[str, str]:
    profile = analysis.get("customer_intent")
    if isinstance(profile, dict) and profile:
        return {str(k): str(v) for k, v in profile.items()}

    answers = analysis.get("guided_answers")
    if isinstance(answers, dict):
        return build_customer_intent_profile(answers)

    iac_params = analysis.get("iac_parameters") if isinstance(analysis.get("iac_parameters"), dict) else {}
    inferred = {
        "arch_deploy_region": iac_params.get("location") or iac_params.get("region"),
        "env_target": iac_params.get("environment"),
        "arch_ha": analysis.get("dr_mode") or infer_dr_mode(analysis),
    }
    return build_customer_intent_profile({k: v for k, v in inferred.items() if v})


def _package_name(analysis: dict[str, Any]) -> str:
    title = str(analysis.get("title") or "").strip()
    if title and title.lower() not in {"azure architecture package", "azure landing zone", "architecture package"}:
        return title

    workload = analysis.get("workload") or analysis.get("workload_name") or analysis.get("application")
    if workload:
        return str(workload).strip()

    zones = analysis.get("zones")
    if isinstance(zones, list):
        for zone in zones:
            if isinstance(zone, dict) and zone.get("name"):
                return str(zone["name"]).strip()

    return "Azure"


def _diagram_analysis(analysis: dict[str, Any], diagram: DiagramVariant) -> dict[str, Any]:
    source = _source_label(analysis)
    package_name = _package_name(analysis)
    title = (
        f"{package_name} — DR Azure Topology ({source} → Azure)"
        if diagram == "dr"
        else f"{package_name} — Target Azure Topology ({source} → Azure)"
    )
    return {**analysis, "title": title}


def _profile_rows(profile: dict[str, str]) -> list[tuple[str, str]]:
    labels = [
        ("environment", "Environment"),
        ("region", "Azure Region"),
        ("availability", "Availability"),
        ("rto", "RTO"),
        ("compliance", "Compliance"),
        ("data_residency", "Residency"),
        ("network_isolation", "Network"),
        ("sku_strategy", "SKU Strategy"),
        ("iac_style", "IaC"),
    ]
    return [(label, profile.get(key, "Not specified")) for key, label in labels]


def _talking_points(analysis: dict[str, Any], profile: dict[str, str]) -> list[tuple[str, str]]:
    regions = infer_regions(analysis, dr_variant="primary")
    dr_mode = infer_dr_mode({**analysis, "regions": regions})
    mappings = [m for m in analysis.get("mappings", []) if isinstance(m, dict)]
    high_conf = sum(1 for m in mappings if float(m.get("confidence") or 0) >= 0.9)
    source = _source_label(analysis)
    target_region = profile.get("region") or regions[0].get("name", "the selected Azure region")

    points = [
        ("Lead with the source-to-target story", f"Translate the detected {source} estate into Azure landing-zone tiers so platform teams can review ingress, compute, data, identity, storage, and observability separately."),
        ("Name the CAF/AVM landing zone assumptions", "Use the caf-avm-baseline profile for hub-spoke networking, private endpoints, managed identities, diagnostic settings, policy, backup, and required workload tags."),
        ("Anchor the deployment region", f"Use {target_region} as the primary deployment anchor and align the topology to {profile.get('availability', 'the stated availability target')}."),
        ("Make security boundaries explicit", f"Apply {profile.get('network_isolation', 'VNet integration')} and {profile.get('data_residency', 'the stated data residency posture')} as design guardrails."),
        ("Keep cost posture visible", f"Keep {profile.get('sku_strategy', 'balanced')} as the commercial posture for sizing and cost discussions."),
    ]
    if high_conf:
        points.append(("Move high-confidence services forward", f"{high_conf} service mappings are high-confidence and can move into implementation planning after owner review."))
    if dr_mode != "single-region":
        points.append(("Review DR before commitment", f"The DR view should be reviewed as a {dr_mode} pattern before committing RTO/RPO or runbook ownership."))
    return points[:6]


def _build_dr_readiness_rubric(analysis: dict[str, Any], profile: dict[str, str]) -> dict[str, Any]:
    context = _dr_readiness_context(analysis, profile)
    dimensions = [
        _score_dr_dimension(
            "backup",
            "Backup",
            context,
            ready_any=("backup", "recovery services", "snapshot", "point-in-time", "pitr", "vault"),
            partial_any=("database", "sql", "storage", "blob", "file"),
            ready_note="Backup policy evidence is present for detected data services.",
            partial_note="Data services are detected, but backup policy, retention, or restore-test inputs are incomplete.",
            gap_note="No backup or restore input was provided for the package.",
        ),
        _score_dr_dimension(
            "replication",
            "Replication",
            context,
            ready_any=("multi-region", "active-passive", "active-standby", "active-active", "geo-replication", "cross-region", "zone-redundant"),
            partial_any=("availability zone", "zone", "ha", "99.9"),
            ready_note="Availability intent indicates multi-region or cross-zone replication.",
            partial_note="High availability is indicated, but cross-region replication evidence is incomplete.",
            gap_note="No replication mode or RPO evidence was provided.",
        ),
        _score_dr_dimension(
            "failover",
            "Failover Routing",
            context,
            ready_any=("front door", "traffic manager", "global load", "failover", "waf", "application gateway"),
            partial_any=("load balancer", "gateway", "ingress"),
            ready_note="Global or regional failover routing services are detected.",
            partial_note="Ingress is detected, but failover routing ownership or probe behavior is incomplete.",
            gap_note="No failover routing component was detected.",
        ),
        _score_dr_dimension(
            "identity",
            "Identity Dependency",
            context,
            ready_any=("entra", "managed identity", "key vault", "rbac", "identity"),
            partial_any=("secret", "iam", "credential", "oauth"),
            ready_note="Identity and secret-management dependencies are represented in the detected services or intent.",
            partial_note="Identity is implied, but dependency recovery order and break-glass ownership are incomplete.",
            gap_note="No identity dependency input was provided.",
        ),
        _score_dr_dimension(
            "durability",
            "Data Durability",
            context,
            ready_any=("zone-redundant", "geo-redundant", "grs", "zrs", "sql", "storage", "blob", "files"),
            partial_any=("database", "data", "file"),
            ready_note="Durable data services or redundancy terms are present in the topology.",
            partial_note="Data services are present, but durability tier and retention commitments are incomplete.",
            gap_note="No durable data-store input was detected.",
        ),
        _score_dr_dimension(
            "observability",
            "Observability",
            context,
            ready_any=("monitor", "application insights", "log analytics", "alerts", "workbooks", "cloudwatch"),
            partial_any=("logging", "metrics", "dashboard"),
            ready_note="Monitoring, logging, or alerting services are included for DR review.",
            partial_note="Telemetry is implied, but alert thresholds and DR dashboard ownership are incomplete.",
            gap_note="No DR observability input was detected.",
        ),
        _score_dr_dimension(
            "runbook",
            "Runbook Completeness",
            context,
            ready_any=("runbook", "game day", "failover test", "owner", "operations"),
            partial_any=("rto", "rpo", "recovery time", "recovery point"),
            ready_note="Runbook, owner, or failover-test evidence is present.",
            partial_note="RTO/RPO intent is present, but runbook owner, test cadence, or rollback steps are incomplete.",
            gap_note="No runbook owner, test cadence, or failover procedure was provided.",
        ),
    ]
    total = sum(int(item["points"]) for item in dimensions)
    score = round((total / (len(dimensions) * 2)) * 100)
    rating = "High readiness" if score >= 80 else "Medium readiness" if score >= 50 else "Low readiness"
    detected = context["detected_services"]
    availability = profile.get("availability") or "availability target not specified"
    summary = f"{availability}; detected services reviewed: {', '.join(detected[:5]) if detected else 'none'}."
    limitations = [str(item["limitation"]) for item in dimensions if item.get("limitation")]
    if not limitations:
        limitations = ["Rubric is still advisory until the customer validates recovery ownership and test evidence."]
    return {
        "schema_version": "dr-readiness-rubric/v1",
        "score": score,
        "rating": rating,
        "summary": summary,
        "dimensions": dimensions,
        "limitations": limitations[:7],
    }


def _dr_readiness_context(analysis: dict[str, Any], profile: dict[str, str]) -> dict[str, Any]:
    text_parts = [str(value) for value in profile.values() if value]
    guided_answers = analysis.get("guided_answers")
    if isinstance(guided_answers, dict):
        text_parts.extend(_flatten_dr_values(guided_answers))
    customer_intent = analysis.get("customer_intent")
    if isinstance(customer_intent, dict):
        text_parts.extend(_flatten_dr_values(customer_intent))
    explicit = analysis.get("dr_readiness") or analysis.get("dr_readiness_inputs")
    if isinstance(explicit, dict):
        text_parts.extend(_flatten_dr_values(explicit))

    detected_services: list[str] = []
    categories: list[str] = []
    for mapping in analysis.get("mappings", []):
        if not isinstance(mapping, dict):
            continue
        service = mapping.get("azure_service") or mapping.get("target") or mapping.get("source_service")
        if service:
            detected_services.append(str(service))
            text_parts.append(str(service))
        if mapping.get("category"):
            categories.append(str(mapping["category"]))
            text_parts.append(str(mapping["category"]))
    for connection in analysis.get("service_connections", []):
        if isinstance(connection, dict):
            text_parts.extend(_flatten_dr_values(connection))

    return {
        "text": " ".join(text_parts).lower(),
        "detected_services": _dedupe(detected_services),
        "categories": _dedupe(categories),
    }


def _score_dr_dimension(
    key: str,
    label: str,
    context: dict[str, Any],
    *,
    ready_any: tuple[str, ...],
    partial_any: tuple[str, ...],
    ready_note: str,
    partial_note: str,
    gap_note: str,
) -> dict[str, Any]:
    text = str(context.get("text") or "")
    if any(term in text for term in ready_any):
        return {
            "key": key,
            "label": label,
            "status": "ready",
            "points": 2,
            "note": _dr_note_with_services(ready_note, context),
        }
    if any(term in text for term in partial_any):
        return {
            "key": key,
            "label": label,
            "status": "partial",
            "points": 1,
            "note": _dr_note_with_services(partial_note, context),
            "limitation": f"{label}: {partial_note}",
        }
    return {
        "key": key,
        "label": label,
        "status": "gap",
        "points": 0,
        "note": gap_note,
        "limitation": f"{label}: {gap_note}",
    }


def _dr_note_with_services(note: str, context: dict[str, Any]) -> str:
    services = context.get("detected_services") or []
    if not services:
        return note
    return f"{note} Detected services: {', '.join(services[:4])}."


def _render_dr_rubric_row(item: dict[str, Any]) -> str:
    status = str(item.get("status") or "gap")
    label = html.escape(str(item.get("label") or "Review item"))
    note = html.escape(str(item.get("note") or "Review required."))
    status_label = html.escape(status.title())
    return (
        '<div class="rubric-row">'
        '<div class="rubric-top">'
        f'<div class="rubric-name">{label}</div>'
        f'<div class="rubric-status {html.escape(status)}">{status_label}</div>'
        '</div>'
        f'<div class="rubric-note">{note}</div>'
        '</div>'
    )


def _flatten_dr_values(value: Any) -> list[str]:
    if isinstance(value, dict):
        parts: list[str] = []
        for item in value.values():
            parts.extend(_flatten_dr_values(item))
        return parts
    if isinstance(value, (list, tuple, set)):
        parts = []
        for item in value:
            parts.extend(_flatten_dr_values(item))
        return parts
    if value is None:
        return []
    return [str(value)]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        cleaned = item.strip()
        key = cleaned.lower()
        if cleaned and key not in seen:
            seen.add(key)
            out.append(cleaned)
    return out


def _source_label(analysis: dict[str, Any]) -> str:
    providers: list[str] = []

    def add_provider(value: Any) -> None:
        provider = normalize_source_provider(value)
        if provider not in providers:
            providers.append(provider)

    declared = analysis.get("source_providers")
    if isinstance(declared, (list, tuple, set)):
        for value in declared:
            add_provider(value)

    source_provider = analysis.get("source_provider")
    if source_provider is not None or not providers:
        add_provider(source_provider)

    mappings = analysis.get("mappings", [])
    if isinstance(mappings, list):
        for mapping in mappings:
            if isinstance(mapping, dict) and mapping.get("source_provider") is not None:
                add_provider(mapping["source_provider"])

    return "/".join(provider.upper() for provider in providers)


def _limitations(analysis: dict[str, Any], profile: dict[str, str]) -> list[tuple[str, str]]:
    warnings = [str(_sanitize_manifest(str(w))) for w in analysis.get("warnings", []) if w]
    mappings = [m for m in analysis.get("mappings", []) if isinstance(m, dict)]
    low_conf = [m for m in mappings if float(m.get("confidence") or 0) < 0.8]
    limits = [("Review warning", warning) for warning in warnings[:5]]
    if low_conf:
        names = ", ".join(str(m.get("azure_service") or m.get("target") or "Unknown") for m in low_conf[:4])
        limits.append(("Validate low-confidence mappings", f"Low-confidence mappings need owner validation before deployment: {names}."))
    if profile.get("compliance") and profile.get("compliance") != "None":
        limits.append(("Validate compliance scope", f"Compliance scope is advisory until validated against the customer's control set: {profile['compliance']}."))
    if profile.get("rto") and profile.get("rto") != "Not required":
        limits.append(("Prove RTO/RPO operations", f"RTO target {profile['rto']} requires backup, replication, failover, and operations runbook validation."))
    alz_lines = alz_profile_summary(analysis)
    if alz_lines:
        limits.append(("Review CAF/AVM landing zone profile", "Generated outputs assume " + "; ".join(alz_lines[:4]) + "."))
    trace_lines = traceability_summary(analysis, limit=3)
    if trace_lines:
        limits.append(("Review IaC traceability evidence", "Generated resources include source-to-Azure lineage: " + "; ".join(trace_lines)))
    if not limits:
        limits.append(("Owner validation required", "No blocking limitations were inferred, but service owners should validate networking, identity, and data dependencies before deployment."))
    return limits[:8]


def _tier_summary(analysis: dict[str, Any]) -> list[tuple[str, list[str]]]:
    tiers = infer_tiers_from_mappings(analysis)
    out: list[tuple[str, list[str]]] = []
    for tier, services in tiers.items():
        names = []
        for service in services[:6]:
            if isinstance(service, dict) and service.get("name"):
                names.append(str(service["name"]))
        out.append((tier, names))
    return out


def _strip_xml_declaration(svg: str) -> str:
    return re.sub(r"^\s*<\?xml[^>]*>\s*", "", svg, count=1)


def _namespace_svg_ids(svg: str, suffix: str) -> str:
    ids = re.findall(r'\bid="([^"]+)"', svg)
    if not ids:
        return svg
    out = svg
    for raw_id in sorted(set(ids), key=len, reverse=True):
        new_id = f"{raw_id}-{suffix}"
        out = re.sub(rf'\bid="{re.escape(raw_id)}"', f'id="{new_id}"', out)
        out = re.sub(rf'url\(#{re.escape(raw_id)}\)', f'url(#{new_id})', out)
        out = re.sub(rf'href="#{re.escape(raw_id)}"', f'href="#{new_id}"', out)
        out = re.sub(rf'xlink:href="#{re.escape(raw_id)}"', f'xlink:href="#{new_id}"', out)
    return out


def _safe_filename(analysis: dict[str, Any]) -> str:
    zones = analysis.get("zones") or []
    name = analysis.get("title") or "diagram"
    if zones and isinstance(zones[0], dict) and zones[0].get("name"):
        name = zones[0]["name"]
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(name)).strip("-")
    return cleaned or "diagram"


def clone_with_customer_intent(analysis: dict[str, Any], answers: dict[str, Any]) -> dict[str, Any]:
    """Return an analysis copy annotated with answer and intent metadata."""
    result = copy.deepcopy(analysis)
    result["guided_answers"] = copy.deepcopy(answers)
    result["customer_intent"] = build_customer_intent_profile(answers)
    return result