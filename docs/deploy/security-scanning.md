# Security scanning and signed releases

Status: current. Each row names the workflow that runs the check; the badges show its latest result on the main branch.

Every change to Ops AI is scanned for vulnerable code and dependencies before it merges, and every release ships with
a list of what is inside it, a scan that stops a release with a fixable critical flaw, a signature and a record of
how it was built. A security team can check each of these for itself with the commands on this page.

[![CodeQL](https://github.com/chanl-ai/ops-ai/actions/workflows/codeql.yml/badge.svg?branch=main)](https://github.com/chanl-ai/ops-ai/actions/workflows/codeql.yml)
[![Dependency check](https://github.com/chanl-ai/ops-ai/actions/workflows/dependency-check.yml/badge.svg?branch=main)](https://github.com/chanl-ai/ops-ai/actions/workflows/dependency-check.yml)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/chanl-ai/ops-ai/badge)](https://scorecard.dev/viewer/?uri=github.com/chanl-ai/ops-ai)
[![Leak scan](https://github.com/chanl-ai/ops-ai/actions/workflows/leak-scan.yml/badge.svg)](https://github.com/chanl-ai/ops-ai/actions/workflows/leak-scan.yml)

## The checks

| Check | What it covers | When | Fails when | Workflow |
|---|---|---|---|---|
| CodeQL code scanning | The Python services and packages, the TypeScript console, SDK and CLI, and the GitHub workflows, with the `security-extended` queries | Every pull request, every merge to main, weekly | A finding is shown on the pull request and under Security, Code scanning | `.github/workflows/codeql.yml` |
| OpenSSF Scorecard | The repository's practices: pinned dependencies, token permissions, branch protection, signed releases, code review and more | Every merge to main, weekly, and when branch protection changes | Each low score appears under Code scanning; the score is published to scorecard.dev | `.github/workflows/scorecard.yml` |
| Dependency check | Every locked version in `uv.lock` and `pnpm-lock.yaml`, against OSV and Sonatype OSS Index | A pull request that changes a lockfile, every merge to main, daily | A critical advisory (CVSS 9.0 or higher) that `deploy/mirror-test/audit-baseline.txt` does not list; every lower advisory is listed in the log | `.github/workflows/dependency-check.yml` |
| Release image scan | Each image of a release, by digest, scanned by Trivy from its SBOM | Every version tag | A critical finding with a fixed version available; the images are then left unsigned | `.github/workflows/release-images.yml` |
| SBOM | A CycloneDX SBOM for each image and for each SDK package as a user installs it | Every release; the SDK SBOMs on every SDK build | Never; it is attached to the release | `release-images.yml`, `sdk-publish.yml` |
| Signature | A keyless cosign signature on each image digest and each SDK file, logged in the public Rekor transparency log | Every release | The workflow verifies each signature right after signing and stops if one does not verify | `release-images.yml`, `sdk-publish.yml` |
| Build provenance | A GitHub build provenance attestation (SLSA provenance) for each image and SDK file, naming the workflow, commit and run that built it | Every release | The attestation step fails | `release-images.yml`, `sdk-publish.yml` |
| Dependabot version updates | Python, npm, GitHub Actions and the Dockerfiles' base images; one grouped pull request per ecosystem | Weekly, for versions at least 30 days old | Not a gate; the pull requests go through the checks above | `.github/dependabot.yml` |
| Leak scan | Tracker ids, home paths and internal trailers in the tree and in pull request text | Every pull request | Any match | `.github/workflows/leak-scan.yml` |

Every action in these workflows is pinned to a full commit SHA, and each workflow's token is read-only unless a job
names the one permission it needs. Trivy is installed as a release binary checked against a fixed SHA-256, because
the release tags of its GitHub Actions were rewritten to malicious commits in March 2026 (GHSA-69fq-xp46-6x23).

## Switched on in the repository settings

These are settings, not files, and the repository owner turns them on.

| Setting | Status |
|---|---|
| Dependabot alerts and security updates | **unverified**: owner to switch on |
| Secret scanning with push protection | **unverified**: owner to switch on |
| Private vulnerability reporting (used by `SECURITY.md`) | **unverified**: owner to switch on |
| Sonatype OSS Index account: secrets `OSSINDEX_USER` (the account's email) and `OSSINDEX_TOKEN` | **unverified**: without them the dependency check runs on OSV only and says so in its log |
| Snyk open source and container monitoring | Not set up; needs an account linked to the organisation |

## Verify a release yourself

Replace `<version>` with the release number, for example `0.1.0`, and `<image>` with one of platform, agents, tools,
models, kb, files, documents, runner, opa, proxy, console or db-scripts.

| Check | Command |
|---|---|
| The image is signed by this repository's release workflow | `cosign verify --certificate-identity-regexp '^https://github.com/chanl-ai/ops-ai/.github/workflows/release-images.yml@' --certificate-oidc-issuer https://token.actions.githubusercontent.com ghcr.io/chanl-ai/ops-ai/<image>:<version>` |
| The image was built by this repository's workflow | `gh attestation verify oci://ghcr.io/chanl-ai/ops-ai/<image>:<version> --repo chanl-ai/ops-ai` |
| Its contents | Download `ops-ai-<image>-<version>.cdx.json` from the release; any CycloneDX tool reads it, for example `trivy sbom ops-ai-<image>-<version>.cdx.json` or Sonatype Nexus Lifecycle |
| An SDK file is signed | `cosign verify-blob --bundle <file>.sigstore.json --certificate-identity-regexp '^https://github.com/chanl-ai/ops-ai/.github/workflows/sdk-publish.yml@' --certificate-oidc-issuer https://token.actions.githubusercontent.com <file>` |
| An SDK file was built here | `gh attestation verify <file> --repo chanl-ai/ops-ai` |

The image SBOM and scan cover the linux/amd64 image; the linux/arm64 image is built from the same commit and
Dockerfile. The scan runs after the push, so a release that fails it has images in the registry that carry no
signature: verifying them fails, which is the signal not to deploy them.

## Run the checks locally

| Check | Command |
|---|---|
| Dependency check | `python3 scripts/deps_audit.py vulns` (needs Docker or `osv-scanner`; set `OSSINDEX_USER` and `OSSINDEX_TOKEN` for OSS Index) |
| Its tests | `uv run pytest -q scripts/tests/test_deps_audit.py` |
| Release steps without publishing | Run the release-images workflow by hand with `proof` set: it builds for linux/amd64, pushes to a registry inside the runner, and runs the SBOM, scan, signing and provenance steps |

## Sources

| Source | Used for |
|---|---|
| GitHub Docs, "About code scanning with CodeQL" and "CodeQL code scanning for compiled languages" (docs.github.com/en/code-security/code-scanning) | Advanced setup, `build-mode: none`, the `security-extended` suite |
| OpenSSF Scorecard and scorecard-action (github.com/ossf/scorecard, github.com/ossf/scorecard-action) | The checks, publishing results, the badge |
| SLSA v1.0, "Build track" (slsa.dev/spec/v1.0/levels) | Provenance generated by the hosted build platform |
| GitHub Docs, "Using artifact attestations to establish provenance for builds" | `attest-build-provenance`, `gh attestation verify` |
| Sigstore, "Signing containers" and "Signing blobs" (docs.sigstore.dev/cosign) | Keyless signing by digest, verifying by certificate identity and issuer |
| CycloneDX specification (cyclonedx.org/specification/overview) | The SBOM format |
| Trivy docs, "SBOM" and "Vulnerability" (trivy.dev) | SBOM generation, scanning an SBOM, `--ignore-unfixed` |
| Aqua Security, GHSA-69fq-xp46-6x23 (github.com/aquasecurity/trivy/security/advisories) | Why Trivy is installed by checksum |
| Sonatype OSS Index, "Authentication required" (ossindex.sonatype.org/doc/auth-required) | The token every request needs since September 2025 |
| GitHub Docs, "Configuration options for the dependabot.yml file" | Ecosystems, groups, cooldown |
| GitHub Docs, "Security hardening for GitHub Actions" | SHA pinning and least-privilege tokens |
