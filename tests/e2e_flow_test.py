#!/usr/bin/env python3
"""
Archmorph E2E Flow Test — 5 Architecture Diagrams (3 AWS + 2 GCP)
=================================================================

Tests the full 9-step translation flow for each diagram:
  1. Upload → 2. Analyze → 3. Guided Questions → 4. Apply Answers →
  5. Export Diagram → 6. Generate IaC → 7. Cost Estimate →
  8. HLD Generation → 9. IaC Chat
"""

import json
import sys
import time
import httpx

API = "https://archmorph-api.icyisland-c0dee6ba.northeurope.azurecontainerapps.io"
TIMEOUT = httpx.Timeout(connect=15, read=180, write=30, pool=15)

DIAGRAMS = [
    {
        "label": "D1 — AWS Web Application Architecture",
        "file": "/Users/idokatz/Desktop/AWS1.png",
        "project_id": "e2e-aws-webapp",
        "source": "aws",
    },
    {
        "label": "D2 — AWS Data Lake (Kinesis/Athena/Glue)",
        "file": "/Users/idokatz/Desktop/Samples/AWS2.PNG",
        "project_id": "e2e-aws-datalake",
        "source": "aws",
    },
    {
        "label": "D3 — AWS Multi-Component (AppSync/Fargate/Neptune)",
        "file": "/Users/idokatz/Desktop/AWS3.png",
        "project_id": "e2e-aws-multicomp",
        "source": "aws",
    },
    {
        "label": "D4 — GCP Opta Architecture (GKE/Cloud SQL)",
        "file": "/Users/idokatz/Desktop/GCP1.png",
        "project_id": "e2e-gcp-opta",
        "source": "gcp",
    },
    {
        "label": "D5 — GCP Digital Marketing (BigQuery/Dataflow)",
        "file": "/Users/idokatz/Desktop/GCP2.png",
        "project_id": "e2e-gcp-digimark",
        "source": "gcp",
    },
]

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
SKIP = "\033[93mSKIP\033[0m"

results = []


def step(name: str, ok: bool, detail: str = ""):
    tag = PASS if ok else FAIL
    print(f"  {tag}  {name}" + (f"  ({detail})" if detail else ""))
    results.append((name, ok, detail))
    return ok


def run_flow(d: dict):
    label = d["label"]
    fpath = d["file"]
    pid = d["project_id"]

    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"{'='*70}")

    client = httpx.Client(base_url=API, timeout=TIMEOUT)

    # ── Step 1: Upload ────────────────────────────────────────
    with open(fpath, "rb") as f:
        resp = client.post(
            f"/api/projects/{pid}/diagrams",
            files={"file": ("diagram.png", f, "image/png")},
        )
    ok = resp.status_code == 200
    diagram_id = resp.json().get("diagram_id", "") if ok else ""
    step(f"[{pid}] 1. Upload", ok, f"diagram_id={diagram_id}")
    if not ok:
        print(f"     Response: {resp.status_code} {resp.text[:200]}")
        return

    # ── Step 2: Analyze ───────────────────────────────────────
    resp = client.post(f"/api/diagrams/{diagram_id}/analyze")
    ok = resp.status_code == 200
    analysis = resp.json() if ok else {}
    mappings = analysis.get("mappings", [])
    n_mappings = len(mappings)
    source = d.get("source", "aws").upper()
    detected = [m.get("source_service", "?") for m in mappings[:8]]
    step(f"[{pid}] 2. Analyze", ok, f"{n_mappings} mappings detected")
    if ok:
        print(f"     Detected {source} services: {', '.join(detected)}")
        if n_mappings > 8:
            print(f"     ... and {n_mappings - 8} more")
        # Show zones
        zones = set()
        for m in mappings:
            notes = m.get("notes", "")
            if "Zone" in notes:
                z = notes.split("Zone ")[-1].split(" ")[0].split(":")[0]
                zones.add(z)
        if zones:
            print(f"     Zones: {', '.join(sorted(zones))}")
    else:
        print(f"     Response: {resp.status_code} {resp.text[:300]}")
        return

    # ── Step 3: Guided Questions ──────────────────────────────
    resp = client.post(f"/api/diagrams/{diagram_id}/questions")
    ok = resp.status_code == 200
    questions = resp.json().get("questions", []) if ok else []
    n_q = len(questions)
    step(f"[{pid}] 3. Guided Questions", ok, f"{n_q} questions generated")
    if ok and questions:
        for q in questions[:5]:
            print(f"     - [{q.get('id')}] {q.get('question', '')[:80]}")
        if n_q > 5:
            print(f"     ... and {n_q - 5} more")

    # ── Step 4: Apply Answers (defaults) ──────────────────────
    resp = client.post(
        f"/api/diagrams/{diagram_id}/apply-answers",
        json={"answers": {}},  # Accept all defaults
    )
    ok = resp.status_code == 200
    refined = resp.json() if ok else {}
    refined_mappings = refined.get("mappings", [])
    warnings = refined.get("warnings", [])
    iac_params = refined.get("iac_parameters", {})
    step(
        f"[{pid}] 4. Apply Answers",
        ok,
        f"{len(refined_mappings)} refined mappings, {len(warnings)} warnings",
    )
    if ok:
        if warnings:
            for w in warnings[:3]:
                print(f"     Warning: {w[:100]}")
        if iac_params:
            print(f"     IaC params: {json.dumps({k: v for k, v in list(iac_params.items())[:5]}, default=str)}")

    # ── Step 5a: Export Excalidraw ────────────────────────────
    resp = client.post(
        f"/api/diagrams/{diagram_id}/export-diagram",
        json={"format": "excalidraw"},
    )
    ok = resp.status_code == 200
    export_data = resp.json() if ok else {}
    content_len = len(export_data.get("content", ""))
    step(f"[{pid}] 5a. Export Excalidraw", ok, f"{content_len} chars")

    # ── Step 5b: Export Draw.io ───────────────────────────────
    resp = client.post(
        f"/api/diagrams/{diagram_id}/export-diagram",
        json={"format": "drawio"},
    )
    ok = resp.status_code == 200
    export_data = resp.json() if ok else {}
    has_graph = "mxGraphModel" in export_data.get("content", "")
    step(f"[{pid}] 5b. Export Draw.io", ok, f"has mxGraphModel={has_graph}")

    # ── Step 5c: Export Visio ─────────────────────────────────
    resp = client.post(
        f"/api/diagrams/{diagram_id}/export-diagram",
        json={"format": "vsdx"},
    )
    ok = resp.status_code == 200
    export_data = resp.json() if ok else {}
    has_visio = "VisioDocument" in export_data.get("content", "")
    step(f"[{pid}] 5c. Export Visio", ok, f"has VisioDocument={has_visio}")

    # ── Step 6a: Generate Terraform ───────────────────────────
    resp = client.post(
        f"/api/diagrams/{diagram_id}/generate",
        params={"format": "terraform"},
    )
    ok = resp.status_code == 200
    iac_data = resp.json() if ok else {}
    code = iac_data.get("code", "")
    has_resource = "resource" in code
    step(
        f"[{pid}] 6a. Generate Terraform",
        ok,
        f"{len(code)} chars, has resource={has_resource}",
    )
    if ok and code:
        # Show first few resource blocks
        lines = code.split("\n")
        resources = [l.strip() for l in lines if l.strip().startswith("resource")]
        for r in resources[:5]:
            print(f"     {r}")
        if len(resources) > 5:
            print(f"     ... and {len(resources) - 5} more resources")

    # ── Step 6b: Generate Bicep ───────────────────────────────
    resp = client.post(
        f"/api/diagrams/{diagram_id}/generate",
        params={"format": "bicep"},
    )
    ok = resp.status_code == 200
    bicep_data = resp.json() if ok else {}
    bicep_code = bicep_data.get("code", "")
    has_bicep = "param" in bicep_code or "resource" in bicep_code
    step(
        f"[{pid}] 6b. Generate Bicep",
        ok,
        f"{len(bicep_code)} chars, has bicep syntax={has_bicep}",
    )

    # ── Step 7: Cost Estimate ─────────────────────────────────
    resp = client.get(f"/api/diagrams/{diagram_id}/cost-estimate")
    ok = resp.status_code == 200
    cost = resp.json() if ok else {}
    total = cost.get("total_monthly_estimate", {})
    low = total.get("low", 0)
    high = total.get("high", 0)
    region = cost.get("region", "?")
    n_services = cost.get("service_count", 0)
    step(
        f"[{pid}] 7. Cost Estimate",
        ok,
        f"${low:,.2f}-${high:,.2f}/mo, {n_services} services, region={region}",
    )
    if ok and cost.get("services"):
        for s in cost["services"][:5]:
            print(
                f"     ${s['monthly_low']:>8,.2f} - ${s['monthly_high']:>8,.2f}  {s['service']}"
            )
        if len(cost["services"]) > 5:
            print(f"     ... and {len(cost['services']) - 5} more services")

    # ── Step 8: HLD Generation ──────────────────────────────
    resp = client.post(f"/api/diagrams/{diagram_id}/generate-hld")
    ok = resp.status_code == 200
    hld_data = resp.json() if ok else {}
    hld = hld_data.get("hld", {})
    markdown = hld_data.get("markdown", "")
    hld_title = hld.get("title", "?")
    n_hld_services = len(hld.get("services", []))
    step(
        f"[{pid}] 8. Generate HLD",
        ok,
        f"{n_hld_services} services, {len(markdown)} chars MD",
    )
    if ok:
        print(f"     Title: {hld_title[:80]}")
        if hld.get("services"):
            for s in hld["services"][:4]:
                print(f"     - {s.get('azure_service', '?')}: {s.get('justification', '')[:60]}")
            if n_hld_services > 4:
                print(f"     ... and {n_hld_services - 4} more services")
        if hld.get("waf_assessment"):
            waf = hld["waf_assessment"]
            pillars = ["reliability", "security", "cost_optimization", "operational_excellence", "performance_efficiency"]
            scores = [f"{p[:3]}={waf.get(p, {}).get('score', '?')}" for p in pillars if p in waf]
            if scores:
                print(f"     WAF: {', '.join(scores)}")

    # ── Step 8b: GET HLD ──────────────────────────────────────
    resp = client.get(f"/api/diagrams/{diagram_id}/hld")
    ok = resp.status_code == 200
    step(f"[{pid}] 8b. GET HLD", ok, "retrieved cached HLD")

    # ── Step 9: IaC Chat ──────────────────────────────────────
    resp = client.post(
        f"/api/diagrams/{diagram_id}/iac-chat",
        json={"message": "Add a Redis cache resource for session management", "format": "terraform"},
    )
    ok = resp.status_code == 200
    chat_data = resp.json() if ok else {}
    chat_reply = chat_data.get("reply", "")
    updated_code = chat_data.get("updated_code", "")
    step(
        f"[{pid}] 9a. IaC Chat (add Redis)",
        ok,
        f"reply={len(chat_reply)} chars, code={len(updated_code)} chars",
    )
    if ok and chat_reply:
        print(f"     Reply: {chat_reply[:120]}...")

    # ── Step 9b: IaC Chat History ─────────────────────────────
    resp = client.get(f"/api/diagrams/{diagram_id}/iac-chat")
    ok = resp.status_code == 200
    history = resp.json().get("messages", []) if ok else []
    step(f"[{pid}] 9b. IaC Chat History", ok, f"{len(history)} messages")

    # ── Step 9c: Clear IaC Chat ───────────────────────────────
    resp = client.delete(f"/api/diagrams/{diagram_id}/iac-chat")
    ok = resp.status_code == 200
    step(f"[{pid}] 9c. Clear IaC Chat", ok, "session cleared")

    client.close()
    print()


# ── Main ──────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("  ARCHMORPH E2E FLOW TEST — 5 Architecture Diagrams (3 AWS + 2 GCP)")
    print("=" * 70)

    for d in DIAGRAMS:
        run_flow(d)

    # ── Summary ───────────────────────────────────────────────
    print("=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    total = len(results)

    for name, ok, detail in results:
        tag = PASS if ok else FAIL
        print(f"  {tag}  {name}  {detail}")

    print(f"\n  Total: {total} steps | {PASS} {passed} | {FAIL} {failed}")
    if failed > 0:
        print("\n  Some steps failed!")
        sys.exit(1)
    else:
        print("\n  All steps passed!")
        sys.exit(0)
