---
name: ops-mirror
description: Install and build Ops AI through a company package mirror (Nexus, Artifactory): set the mirror, test it, find the locked versions it does not serve, and install through it. Use when installs fail behind a proxy or a bank's network has no public internet.
allowed-tools: Bash(make *) Bash(uv run *) Bash(python3 *) Read Grep Glob
---

# ops-mirror: work behind a company mirror

<!-- Generated from `docs/guide/skills/ops-mirror.md` by `scripts/agent_skills.py`; change the page, not this file. -->

Make targets: make setup, make deps-doctor, make install-mirror, make deps-relock MIRROR=1.

## When to use it

The machine reaches packages only through a mirror.

## Steps

1. `make setup` with the mirror answers (`PYPI_MIRROR`, `NPM_MIRROR`, `IMAGE_REGISTRY`) tests that each mirror serves a
   locked file and writes `UV_DEFAULT_INDEX`, `NPM_CONFIG_REGISTRY` and `OPS_BASE_IMAGE_PREFIX`.
2. `make deps-doctor` asks the mirror for every locked version and lists the ones it blocks; they go into
   `.mirror/constraints.txt` and `.mirror/npm-overrides.json`.
3. `make deps-relock MIRROR=1` locks within what the mirror serves; `make install-mirror` installs the locked
   versions from it.
4. Every other download has its own setting (`docs/deploy/install.md`, "Behind a company mirror").

## Proof

```bash proof
make deps-doctor
```
