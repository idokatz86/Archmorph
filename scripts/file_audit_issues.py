#!/usr/bin/env python3
"""File GitHub issues for the 2026-05-08 multi-agent audit.

Parses sections 4.1–4.10 of `docs/audits/2026-05-08-cto-multi-agent-audit.md`
and creates one issue per `#### F-<prefix>-<n>` block via `gh issue create`.

Usage:
    python scripts/file_audit_issues.py --dry-run   # parse + show first 3 issues
    python scripts/file_audit_issues.py             # file all issues
    python scripts/file_audit_issues.py --start 50  # resume after a failure

Writes results to `docs/audits/2026-05-08-cto-multi-agent-audit.issues.json`.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AUDIT_MD = REPO_ROOT / "docs" / "audits" / "2026-05-08-cto-multi-agent-audit.md"
RESULTS_JSON = REPO_ROOT / "docs" / "audits" / "2026-05-08-cto-multi-agent-audit.issues.json"

# Map finding prefix -> agent label
PREFIX_AGENT = {
    "BE": "agent:backend-master",
    "FE": "agent:fe-master",
    "UX": "agent:ux-master",
    "PERF": "agent:performance-master",
    "API": "agent:api-master",
    "QA": "agent:qa-master",
    "SEC": "agent:ciso-master",
    "DO": "agent:devops-master",
    "CL": "agent:cloud-master",
    "BUG": "agent:bug-master",
}


@dataclass
class Finding:
    fid: str           # e.g. "F-BE-1"
    prefix: str        # e.g. "BE"
    title: str         # short title from header line
    body: str          # full finding markdown body
    severity: str = "P3"

    def issue_title(self) -> str:
        return f"[Audit 2026-05-08] {self.fid}: {self.title}"

    def issue_labels(self) -> list[str]:
        labels = ["audit:2026-05-08"]
        labels.append(f"severity:{self.severity}")
        agent = PREFIX_AGENT.get(self.prefix)
        if agent:
            labels.append(agent)
        return labels

    def issue_body(self) -> str:
        return (
            f"> Auto-filed by Scrum Master from CTO-led multi-agent audit run.\n"
            f"> Audit doc: [docs/audits/2026-05-08-cto-multi-agent-audit.md]"
            f"(../blob/main/docs/audits/2026-05-08-cto-multi-agent-audit.md)\n"
            f"> Finding ID: **{self.fid}**\n\n"
            f"---\n\n"
            f"{self.body}\n\n"
            f"---\n\n"
            f"**Definition of done:** All items in *Acceptance criteria* above are met "
            f"and a regression test exists if applicable."
        )


SEVERITY_RE = re.compile(r"\*\*Severity:\*\*\s*(P[0-3])")
HEADING_RE = re.compile(r"^####\s+(F-[A-Z]+-\d+)\.\s+(.+?)\s*$")


def parse_findings(md: str) -> list[Finding]:
    """Walk the markdown; emit one Finding per `#### F-...` block."""
    lines = md.splitlines()
    findings: list[Finding] = []
    cur_lines: list[str] = []
    cur_fid: str | None = None
    cur_title: str | None = None
    in_findings_section = False

    for ln in lines:
        # Section gate: only collect inside `## 4. Findings Consolidation`
        if ln.startswith("## 4. Findings Consolidation"):
            in_findings_section = True
            continue
        if ln.startswith("## ") and in_findings_section and not ln.startswith(
            "## 4. Findings Consolidation"
        ):
            in_findings_section = False
            # flush current
            if cur_fid and cur_title is not None:
                findings.append(_flush(cur_fid, cur_title, cur_lines))
                cur_fid = cur_title = None
                cur_lines = []
            continue
        if not in_findings_section:
            continue

        m = HEADING_RE.match(ln)
        if m:
            if cur_fid and cur_title is not None:
                findings.append(_flush(cur_fid, cur_title, cur_lines))
            cur_fid, cur_title = m.group(1), m.group(2).strip()
            cur_lines = []
        else:
            if cur_fid is not None:
                cur_lines.append(ln)

    if cur_fid and cur_title is not None:
        findings.append(_flush(cur_fid, cur_title, cur_lines))

    return findings


def _flush(fid: str, title: str, lines: list[str]) -> Finding:
    body = "\n".join(lines).strip()
    sev_m = SEVERITY_RE.search(body)
    severity = sev_m.group(1) if sev_m else "P3"
    prefix = fid.split("-")[1]
    return Finding(fid=fid, prefix=prefix, title=title, body=body, severity=severity)


def file_issue(f: Finding, dry: bool) -> dict:
    cmd = [
        "gh", "issue", "create",
        "--title", f.issue_title(),
        "--body", f.issue_body(),
    ]
    for lbl in f.issue_labels():
        cmd.extend(["--label", lbl])

    if dry:
        return {
            "fid": f.fid,
            "title": f.issue_title(),
            "labels": f.issue_labels(),
            "dry_run": True,
        }

    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
    if result.returncode != 0:
        return {
            "fid": f.fid,
            "title": f.issue_title(),
            "error": result.stderr.strip() or result.stdout.strip(),
            "returncode": result.returncode,
        }

    url = result.stdout.strip().splitlines()[-1]
    number = None
    m = re.search(r"/issues/(\d+)$", url)
    if m:
        number = int(m.group(1))
    return {
        "fid": f.fid,
        "title": f.issue_title(),
        "url": url,
        "number": number,
        "labels": f.issue_labels(),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--start", type=int, default=0,
                   help="Resume after this index (0-based)")
    p.add_argument("--limit", type=int, default=None,
                   help="Cap total filings (debug)")
    p.add_argument("--delay", type=float, default=0.7,
                   help="Seconds between filings (rate-limit guard)")
    args = p.parse_args()

    md = AUDIT_MD.read_text(encoding="utf-8")
    findings = parse_findings(md)
    print(f"[parse] found {len(findings)} findings")

    sev_counts = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    for f in findings:
        sev_counts[f.severity] = sev_counts.get(f.severity, 0) + 1
    print(f"[parse] severity counts: {sev_counts}")

    if args.dry_run:
        print("\n=== DRY RUN: first 3 findings ===\n")
        for f in findings[:3]:
            print(f"--- {f.fid} ({f.severity}) ---")
            print(f"Title:  {f.issue_title()}")
            print(f"Labels: {f.issue_labels()}")
            print(f"Body (first 200 chars):\n{f.issue_body()[:200]}\n")
        return 0

    # Load existing results to resume
    results: list[dict] = []
    already_filed: set[str] = set()
    if RESULTS_JSON.exists():
        try:
            results = json.loads(RESULTS_JSON.read_text(encoding="utf-8"))
            already_filed = {r["fid"] for r in results if r.get("number")}
            print(f"[resume] loaded {len(results)} prior results "
                  f"({len(already_filed)} successfully filed)")
        except Exception as exc:
            print(f"[resume] could not load existing results: {exc}")
            results = []

    findings_to_file = [f for f in findings if f.fid not in already_filed]
    if args.start:
        findings_to_file = findings_to_file[args.start:]
    if args.limit:
        findings_to_file = findings_to_file[: args.limit]

    print(f"[run] filing {len(findings_to_file)} issues "
          f"(skipping {len(findings) - len(findings_to_file)} already done)")

    for i, f in enumerate(findings_to_file, 1):
        print(f"  [{i}/{len(findings_to_file)}] {f.fid} ({f.severity}) ...",
              end=" ", flush=True)
        res = file_issue(f, dry=False)
        results.append(res)

        # Persist after each filing for crash safety
        RESULTS_JSON.write_text(
            json.dumps(results, indent=2) + "\n", encoding="utf-8"
        )

        if "error" in res:
            print(f"ERROR: {res['error'][:120]}")
            # Likely secondary rate limit; back off
            if "secondary rate limit" in res["error"].lower():
                print("    backing off 60s for rate limit")
                time.sleep(60)
        else:
            print(f"#{res.get('number')} {res.get('url', '?')}")

        time.sleep(args.delay)

    # Summary
    ok = [r for r in results if r.get("number")]
    err = [r for r in results if r.get("error")]
    print(f"\n[done] filed: {len(ok)}, errors: {len(err)}")
    if err:
        print("Errors:")
        for r in err:
            print(f"  {r['fid']}: {r['error'][:140]}")
    return 0 if not err else 1


if __name__ == "__main__":
    sys.exit(main())
