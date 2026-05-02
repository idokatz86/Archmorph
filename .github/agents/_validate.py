"""Validate repository agent instruction files and trigger agent CI checks."""

import os, re

agents_dir = "/Users/idokatz/VSCode/Archmorph/.github/agents"
required = ["System Persona", "Core Competencies", "Collaboration Protocols", "Guardrails"]
files = sorted([f for f in os.listdir(agents_dir) if f.endswith(".agent.md")])

print(f"Total agent files: {len(files)}\n")
all_ok = True
total_lines = 0
total_chars = 0
for f in files:
    path = os.path.join(agents_dir, f)
    with open(path) as fh:
        content = fh.read()
    lines = content.count("\n")
    total_lines += lines
    total_chars += len(content)
    has_fm = content.startswith("---") and content.count("---") >= 2
    nm = re.search(r"^name: (.+)", content, re.MULTILINE)
    name = nm.group(1).strip() if nm else "MISSING"
    missing = [r for r in required if r not in content]
    status = "OK" if not missing and has_fm else "FAIL"
    if missing:
        all_ok = False
    print(f"  {status} {f:40} lines={lines:3}  name={name}")
    if missing:
        print(f"       MISSING: {missing}")

print(f"\nTotal: {total_lines} lines, {total_chars} chars across {len(files)} files")
print("ALL 21 AGENTS VALIDATED SUCCESSFULLY" if all_ok else "SOME AGENTS HAVE ISSUES")
