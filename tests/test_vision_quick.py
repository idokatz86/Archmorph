#!/usr/bin/env python3
"""Quick test of the enhanced vision analyzer on all 3 diagrams."""
import json
import sys
sys.path.insert(0, "/Users/idokatz/VSCode/Archmorph/backend")
from vision_analyzer import analyze_image

DIAGRAMS = [
    ("Call Center", "/Users/idokatz/Desktop/1.png"),
    ("ArteraAI Medical", "/Users/idokatz/Desktop/2.png"),
    ("Bitbucket VPC", "/Users/idokatz/Desktop/3.png"),
]

for idx, (label, path) in enumerate(DIAGRAMS, 1):
    with open(path, "rb") as f:
        img = f.read()
    print(f"\n{'='*60}")
    print(f"  Diagram {idx}: {label} ({len(img)} bytes)")
    print(f"{'='*60}")
    r = analyze_image(img, "image/png")
    print(f"  Type:     {r['diagram_type']}")
    print(f"  Services: {r['services_detected']} | Provider: {r['source_provider']}")
    print(f"  Patterns: {r.get('architecture_patterns', [])}")

    unmapped = [m for m in r["mappings"] if "Manual mapping" in m["azure_service"]]
    mapped = [m for m in r["mappings"] if "Manual mapping" not in m["azure_service"]]
    print(f"  Mapped:   {len(mapped)} | Unmapped: {len(unmapped)}")

    for z in r["zones"]:
        svcs = z["services"]
        svc_strs = []
        for s in svcs:
            k = "aws" if "aws" in s else "gcp"
            tag = "X" if "Manual" in s["azure"] else "OK"
            svc_strs.append(f"{s[k]}({tag})")
        print(f"    [{z['name']}] {', '.join(svc_strs)}")

    if unmapped:
        print(f"  Unmapped: {[m['source_service'] for m in unmapped]}")
    print(f"  Confidence: avg={r['confidence_summary']['average']}")
    print(f"  Warnings: {len(r['warnings'])}")
    for w in r["warnings"][:3]:
        print(f"    - {w[:90]}")

print("\n  Done!")
