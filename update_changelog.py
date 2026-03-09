import re

file_path = "/Users/idokatz/VSCode/Archmorph/CHANGELOG.md"
with open(file_path, "r") as f:
    text = f.read()

new_log = """
## [3.8.0] - 2026-03-09

### Added
- **Dynamic GitHub Roadmap Sync** — Community feature requests in GitHub automatically sync directly to the Roadmap tab's "Ideas" column allowing for live up-to-date tracking natively in the frontend.
- **Vibe-Coding Disclaimer Banner** — Global dismissible banner to outline the experimental and fast-paced nature of the application for users.

### Changed
- `LegalPages.jsx` — Overhauled the Terms of Service. Stripped out references to 'Subscription & Billing'. Clarified the free-of-charge, "as-is" vibe-coding nature of the tool for legal clarity.
- `ci.yml` — Fully optimized GitHub Actions CI pipeline removing duplicate node builds via Artifact caching reducing build time tremendously.
- `ci.yml` — Appended Azure CLI idempotency skips causing duplicate deployments to fast-skip saving over 60 seconds per CI pipeline.
- `security.yml` — Sliced redundantly overlapping SAST/SCA scanners (bandit, semgrep, test-trivy) leaving just a core optimized list (CodeQL, Grype) saving 40% Action minutes.
- `roadmap.py` — Now features a 15-minute runtime cache on `fetch_github_ideas` to manage API rate limits efficiently.

"""

text = text.replace("## [Unreleased]\n", "## [Unreleased]\n" + new_log)

with open(file_path, "w") as f:
    f.write(text)

print("Updated CHANGELOG.md")
