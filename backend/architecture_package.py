"""Customer-facing architecture package exports.

The package renderer keeps Archmorph's architecture analysis as the source of
truth and treats HTML/SVG as presentation targets. It composes the existing
Azure Landing Zone SVG renderer with a small customer-intent profile and
customer-safe talking points.
"""

from __future__ import annotations

import copy
import html
import re
from typing import Any, Literal

from azure_landing_zone import generate_landing_zone_svg
from azure_landing_zone_schema import infer_dr_mode, infer_regions, infer_tiers_from_mappings
from customer_intent import build_customer_intent_profile


PackageFormat = Literal["html", "svg"]
DiagramVariant = Literal["primary", "dr"]

def generate_architecture_package(
    analysis: dict[str, Any],
    *,
    format: PackageFormat = "html",
    diagram: DiagramVariant = "primary",
) -> dict[str, str]:
    """Generate the architecture package in HTML or SVG form."""
    if format not in ("html", "svg"):
        raise ValueError("format must be 'html' or 'svg'")
    if diagram not in ("primary", "dr"):
        raise ValueError("diagram must be 'primary' or 'dr'")
    if not isinstance(analysis, dict):
        raise ValueError("analysis must be a dict")

    if format == "svg":
        result = generate_landing_zone_svg(analysis, dr_variant=diagram)
        return {
            "format": "architecture-package-svg",
            "filename": result["filename"].replace("landing-zone", "architecture-package"),
            "content": result["content"],
        }

    primary_svg = _namespace_svg_ids(
        _strip_xml_declaration(generate_landing_zone_svg(analysis, dr_variant="primary")["content"]),
        "primary",
    )
    dr_svg = _namespace_svg_ids(
        _strip_xml_declaration(generate_landing_zone_svg(analysis, dr_variant="dr")["content"]),
        "dr",
    )
    content = _render_html_package(analysis, primary_svg, dr_svg)
    return {
        "format": "architecture-package-html",
        "filename": f"archmorph-{_safe_filename(analysis)}-architecture-package.html",
        "content": content,
    }


def _render_html_package(analysis: dict[str, Any], primary_svg: str, dr_svg: str) -> str:
    title = html.escape(str(analysis.get("title") or "Azure Architecture Package"))
    source = html.escape(str(analysis.get("source_provider") or "AWS").upper())
    profile = _profile_from_analysis(analysis)
    intent_rows = "\n".join(
        f"<div><span>{html.escape(label)}</span><strong>{html.escape(value)}</strong></div>"
        for label, value in _profile_rows(profile)
    )
    talking_points = "\n".join(
        f"<li>{html.escape(point)}</li>" for point in _talking_points(analysis, profile)
    )
    limitations = "\n".join(
        f"<li>{html.escape(item)}</li>" for item in _limitations(analysis, profile)
    )
    tier_summary = "\n".join(
        f"<li><strong>{html.escape(tier.title())}</strong><span>{html.escape(', '.join(names) or 'No service inferred')}</span></li>"
        for tier, names in _tier_summary(analysis)
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>
    :root {{ color-scheme: light; --ink:#172033; --muted:#526178; --line:#d9e0ea; --azure:#0078d4; --bg:#f6f8fb; --card:#ffffff; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); color: var(--ink); font-family: "Segoe UI", system-ui, -apple-system, BlinkMacSystemFont, sans-serif; }}
    header {{ padding: 22px 28px 16px; background: #fff; border-bottom: 1px solid var(--line); }}
    h1 {{ margin: 0; font-size: 24px; line-height: 1.2; letter-spacing: 0; }}
    header p {{ margin: 6px 0 0; color: var(--muted); font-size: 13px; }}
    nav {{ display: flex; gap: 8px; padding: 12px 28px; background: #fff; border-bottom: 1px solid var(--line); position: sticky; top: 0; z-index: 2; }}
    button.tab {{ border: 1px solid var(--line); background: #fff; color: var(--ink); border-radius: 8px; padding: 8px 12px; font: inherit; font-size: 13px; cursor: pointer; }}
    button.tab[aria-selected="true"] {{ background: var(--azure); border-color: var(--azure); color: #fff; }}
    main {{ padding: 20px 28px 32px; }}
    section.panel {{ display: none; }}
    section.panel.active {{ display: block; }}
    .diagram {{ overflow: auto; background: #fff; border: 1px solid var(--line); border-radius: 8px; padding: 12px; }}
    .diagram svg {{ width: 100%; min-width: 1100px; height: auto; display: block; }}
    .grid {{ display: grid; grid-template-columns: minmax(280px, 0.8fr) minmax(420px, 1.2fr); gap: 16px; align-items: start; }}
    .block {{ background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 16px; }}
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
    @media (max-width: 900px) {{ .grid {{ grid-template-columns: 1fr; }} nav {{ overflow-x: auto; }} main, header, nav {{ padding-left: 16px; padding-right: 16px; }} }}
  </style>
</head>
<body>
  <header>
    <h1>{title}</h1>
    <p>{source} to Azure architecture package with target topology, customer intent, talking points, and known constraints.</p>
  </header>
  <nav aria-label="Architecture package sections">
    <button class="tab" type="button" data-tab="as-is" aria-selected="true">Target Topology</button>
    <button class="tab" type="button" data-tab="dr" aria-selected="false">DR Topology</button>
    <button class="tab" type="button" data-tab="talking" aria-selected="false">Talking Points</button>
    <button class="tab" type="button" data-tab="limits" aria-selected="false">Limitations</button>
  </nav>
  <main>
    <section id="as-is" class="panel active"><div class="diagram">{primary_svg}</div></section>
    <section id="dr" class="panel"><div class="diagram">{dr_svg}</div></section>
    <section id="talking" class="panel"><div class="grid"><div class="block"><h2>Customer Intent</h2><div class="intent">{intent_rows}</div></div><div class="block"><h2>Recommended Narrative</h2><ul>{talking_points}</ul></div></div></section>
    <section id="limits" class="panel"><div class="grid"><div class="block"><h2>Service Tiers</h2><ul class="tiers">{tier_summary}</ul></div><div class="block"><h2>Assumptions And Constraints</h2><ul>{limitations}</ul></div></div></section>
  </main>
  <script>
    document.querySelectorAll('button.tab').forEach((button) => {{
      button.addEventListener('click', () => {{
        document.querySelectorAll('button.tab').forEach((tab) => tab.setAttribute('aria-selected', 'false'));
        document.querySelectorAll('section.panel').forEach((panel) => panel.classList.remove('active'));
        button.setAttribute('aria-selected', 'true');
        document.getElementById(button.dataset.tab).classList.add('active');
      }});
    }});
  </script>
</body>
</html>"""


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


def _talking_points(analysis: dict[str, Any], profile: dict[str, str]) -> list[str]:
    regions = infer_regions(analysis, dr_variant="primary")
    dr_mode = infer_dr_mode({**analysis, "regions": regions})
    mappings = [m for m in analysis.get("mappings", []) if isinstance(m, dict)]
    high_conf = sum(1 for m in mappings if float(m.get("confidence") or 0) >= 0.9)
    source = str(analysis.get("source_provider") or "AWS").upper()
    target_region = profile.get("region") or regions[0].get("name", "the selected Azure region")

    points = [
        f"Translate the detected {source} estate into Azure landing-zone tiers so platform teams can review ingress, compute, data, identity, storage, and observability separately.",
        f"Use {target_region} as the primary deployment anchor and align the topology to {profile.get('availability', 'the stated availability target')}.",
        f"Apply {profile.get('network_isolation', 'VNet integration')} and {profile.get('data_residency', 'the stated data residency posture')} as design guardrails.",
        f"Keep {profile.get('sku_strategy', 'balanced')} as the commercial posture for sizing and cost discussions.",
    ]
    if high_conf:
        points.append(f"{high_conf} service mappings are high-confidence and can move into implementation planning after owner review.")
    if dr_mode != "single-region":
        points.append(f"The DR view should be reviewed as a {dr_mode} pattern before committing RTO/RPO or runbook ownership.")
    return points[:6]


def _limitations(analysis: dict[str, Any], profile: dict[str, str]) -> list[str]:
    warnings = [str(w) for w in analysis.get("warnings", []) if w]
    mappings = [m for m in analysis.get("mappings", []) if isinstance(m, dict)]
    low_conf = [m for m in mappings if float(m.get("confidence") or 0) < 0.8]
    limits = warnings[:5]
    if low_conf:
        names = ", ".join(str(m.get("azure_service") or m.get("target") or "Unknown") for m in low_conf[:4])
        limits.append(f"Low-confidence mappings need owner validation before deployment: {names}.")
    if profile.get("compliance") and profile.get("compliance") != "None":
        limits.append(f"Compliance scope is advisory until validated against the customer's control set: {profile['compliance']}.")
    if profile.get("rto") and profile.get("rto") != "Not required":
        limits.append(f"RTO target {profile['rto']} requires backup, replication, failover, and operations runbook validation.")
    if not limits:
        limits.append("No blocking limitations were inferred, but service owners should validate networking, identity, and data dependencies before deployment.")
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