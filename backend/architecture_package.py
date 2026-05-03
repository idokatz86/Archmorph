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

from azure_landing_zone import generate_landing_zone_svg
from azure_landing_zone_schema import infer_dr_mode, infer_regions, infer_tiers_from_mappings
from customer_intent import build_customer_intent_profile
from source_provider import normalize_source_provider


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
        manifest = _build_manifest(
            analysis,
            format=format,
            diagram=diagram,
            analysis_id=analysis_id,
            artifact_filenames=[filename],
        )
        return {
            "format": "architecture-package-svg",
            "filename": filename,
            "content": _embed_svg_manifest(result["content"], manifest),
            "manifest": manifest,
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
    manifest = _build_manifest(
        analysis,
        format=format,
        diagram=diagram,
        analysis_id=analysis_id,
        artifact_filenames=[filename, target_filename, dr_filename],
    )
    content = _render_html_package(analysis, primary_svg, dr_svg, manifest)
    return {
        "format": "architecture-package-html",
        "filename": filename,
        "content": content,
        "manifest": manifest,
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
    tier_summary = "\n".join(
        f"<li><strong>{html.escape(tier.title())}</strong><span>{html.escape(', '.join(names) or 'Review required')}</span></li>"
        for tier, names in _tier_summary(analysis)
    )

    manifest_json = _manifest_json(manifest)
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
    nav {{ display: grid; grid-template-columns: repeat(4, minmax(180px, 1fr)); gap: 10px; margin-bottom: 14px; position: sticky; top: 0; z-index: 2; background: rgba(246, 248, 251, 0.94); padding: 8px 0; backdrop-filter: blur(8px); }}
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
        .insight-list {{ display: grid; gap: 10px; }}
        .insight-row {{ border: 1px solid #e7edf5; border-radius: 8px; padding: 12px; background: #fbfdff; }}
        .insight-h {{ font-size: 13px; font-weight: 800; color: var(--ink); margin-bottom: 5px; }}
        .insight-b {{ font-size: 13px; line-height: 1.5; color: #314158; }}
        footer {{ margin-top: 16px; color: var(--muted); font-size: 12px; }}
        @media (max-width: 900px) {{ .shell {{ padding: 12px; }} header {{ flex-direction: column; }} .meta-pills {{ justify-content: flex-start; }} .grid {{ grid-template-columns: 1fr; }} nav {{ grid-template-columns: 1fr; position: static; }} }}
  </style>
</head>
<body>
    <div class="shell">
    <header>
        <div class="brand"><div class="mark">A↻</div><div><h1>{title}</h1><p>Cross-cloud architecture translation and Azure hardening package</p></div></div>
        <div class="meta-pills"><span class="brand-pill">Customer / workload: {display_name}</span><span class="brand-pill">Source: {source}</span><span class="brand-pill">Target: Azure</span><span class="brand-pill">Region: {target_region}</span></div>
    </header>
    <div class="story"><strong>{source_file}</strong><span>→</span><span>Archmorph produced four review outputs:</span><span class="brand-pill">A · Target</span><span class="brand-pill">B · DR</span><span class="brand-pill">C · Talking Points</span><span class="brand-pill">D · Limitations</span></div>
    <nav aria-label="Architecture package sections">
        <button class="tab" type="button" data-tab="as-is" aria-selected="true">A — Target Azure Topology<span>customer-ready package</span></button>
        <button class="tab" type="button" data-tab="dr" aria-selected="false">B — DR Topology<span>resilience review</span></button>
        <button class="tab" type="button" data-tab="talking" aria-selected="false">C — Talking Points<span>customer-facing narrative</span></button>
        <button class="tab" type="button" data-tab="limits" aria-selected="false">D — Services Limitations<span>technical gotchas</span></button>
    </nav>
    <main>
    <section id="as-is" class="panel active"><div class="diagram">{primary_svg}</div></section>
    <section id="dr" class="panel"><div class="diagram">{dr_svg}</div></section>
        <section id="talking" class="panel"><div class="grid"><div class="block"><h2>Customer Intent</h2><div class="intent">{intent_rows}</div></div><div class="block"><h2>Recommended Narrative</h2><div class="insight-list">{talking_points}</div></div></div></section>
        <section id="limits" class="panel"><div class="grid"><div class="block"><h2>Service Tiers</h2><ul class="tiers">{tier_summary}</ul></div><div class="block"><h2>Assumptions And Constraints</h2><div class="insight-list">{limitations}</div></div></div></section>
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
  </script>
  <script type="application/json" id="archmorph-artifact-manifest">{html.escape(manifest_json)}</script>
</body>
</html>"""


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
    if format == "svg":
        return [(filenames[0], "selected-topology", "svg")]
    roles = ["architecture-package-html", "target-topology-svg", "dr-topology-svg"]
    formats = ["html", "svg", "svg"]
    return list(zip(filenames, roles, formats))


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
        ("Anchor the deployment region", f"Use {target_region} as the primary deployment anchor and align the topology to {profile.get('availability', 'the stated availability target')}."),
        ("Make security boundaries explicit", f"Apply {profile.get('network_isolation', 'VNet integration')} and {profile.get('data_residency', 'the stated data residency posture')} as design guardrails."),
        ("Keep cost posture visible", f"Keep {profile.get('sku_strategy', 'balanced')} as the commercial posture for sizing and cost discussions."),
    ]
    if high_conf:
        points.append(("Move high-confidence services forward", f"{high_conf} service mappings are high-confidence and can move into implementation planning after owner review."))
    if dr_mode != "single-region":
        points.append(("Review DR before commitment", f"The DR view should be reviewed as a {dr_mode} pattern before committing RTO/RPO or runbook ownership."))
    return points[:6]


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