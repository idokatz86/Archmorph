# Vendored security packages

The remaining brace-expansion archives preserve the patched expansion bounds and the callable CommonJS API required by legacy Minimatch consumers. Each archive comes from an immutable upstream release tag and is pinned as a direct dependency so npm overrides can safely reference it with `$dependency`.

## `brace-expansion-5.0.12.tgz`

Release tarball retrieved with `npm pack brace-expansion@5.0.12` from the approved
Microsoft public npm feed. The corresponding upstream tag `v5.0.12` resolves to
commit `f3410159d768f56c9d9f4511d3e1b46425fc1099`; the tag is unsigned.

- Upstream: `https://github.com/juliangruber/brace-expansion`
- Fixes include the original expansion bound and follow-up denial-of-service
  advisories GHSA-rgw5-rvv9-x895, GHSA-q2hr-2g5m-vwhr, GHSA-qhr7-859c-m2p7,
  and GHSA-6j4f-fj2g-mc7p.
- SHA-256: `ef8448ec78f20b692f04fa6d01f39b5ab34c66404bea3429f5a39c6c9e0be8b4`

## `brace-expansion-5.0.12-compat.tgz`

Deterministic derivative of `brace-expansion-5.0.12.tgz` used by the frontend. Its only content change is an exact suffix on `dist/commonjs/index.js` that restores the callable CommonJS export expected by legacy Minimatch consumers. The ESM API and all expansion logic remain byte-for-byte identical to the pinned source archive.

- Build recipe: `python scripts/build_brace_expansion_compat.py`
- Verification: `python scripts/build_brace_expansion_compat.py --check`
- SHA-256: `f2d69051f00a8e90a2ba1d9190aacb5da7b3b82228c46d42bca0876b872d27ca`

`scripts/verify_vendored_packages.py` verifies both archives and rejects any compatibility delta beyond that approved suffix.

## Retired archives

The js-yaml, Nano ID, and PostCSS archives have been replaced by public-registry
dependencies with patched minimum versions: js-yaml 4.3.2, Nano ID 3.3.18, and
PostCSS 8.5.23. Their integrity hashes are recorded in the npm lockfiles.
Dependency overrides still apply these fixes to transitive consumers.

The package behavior checks remain mandatory, including the merge-key limit,
non-positive ID sizes, and source-map path isolation. Do not restore the obsolete
archives to work around installation or audit failures.

## Public registry selection

The project npm configurations and Dependabot use the unauthenticated Microsoft
public npm feed:

`https://ms-feed-25.pkgs.visualstudio.com/1es-public/_packaging/npm-public/npm/registry/`

This source change was explicitly approved during the October 2026 maintenance
review. At verification time, npmjs.org returned 404 for patched releases including
js-yaml 4.3.2 and DOMPurify 3.4.16, while the public feed served them without
credentials. Lockfiles retain SHA-512 integrity verification; existing npmjs.org
tarball references remain supported. Do not replace feed URLs with npmjs.org URLs
without checking that the exact versions and integrity hashes are available there.

Use `npm ci` in both the repository root and `frontend`, then run
`npm audit --audit-level=low`. The frontend also requires
`npm run test:security-packages`, lint, unit tests, and a production build.

After resolving dependency updates, run `npm run security:lock-integrity` from the
repository root before committing the lockfiles. Some feed metadata supplies only
SHA-1 checksums. This explicit maintenance command downloads only approved-feed
archives, verifies their existing pins, and writes SHA-512 candidates alongside
the inputs as `package-lock.json.sha512`. It never writes the input lockfiles and
refuses to overwrite an existing candidate. Already strengthened inputs produce
no candidate.

Review each candidate against its current lockfile, stop npm/editor writers, and
apply only the verified integrity changes through your normal review workflow.
Delete the candidate after review. This separate publication step prevents an
edit arriving after verification from being silently overwritten by the tool.
Download errors, checksum mismatches, unexpected sources, and changes observed
during verification fail explicitly.

Re-run clean installs to verify the resulting pins. Do not weaken the integrity
regression checks or silently rewrite lockfiles during CI; Dependabot updates may
need this reviewed maintenance step.

## Removal policy

Replace each file dependency with its public-registry release and remove its archive once that exact or newer patched version is published, parent-tool compatibility is verified, and clean-install audits remain green. Remove the upstream and compatibility brace-expansion archives together once legacy Minimatch consumers support the patched registry release without adaptation.
