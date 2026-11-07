# Images: what every container runs at start

Status: current.

These files are copied into the images `../fly/Dockerfile` builds and are the same in every target (compose, k8s,
Fly, the release package). Deploy-wide rules: [../CLAUDE.md](../CLAUDE.md).

| File | Role |
|---|---|
| `entrypoint.sh` | Every service image's entrypoint: `migrate [chain...]` runs `migrate.sh`, anything else runs as given. Settings come from `OPS_*` values or files under `/run/secrets` named after the setting |
| `chains` | The migration chains in run order; `migrate.sh`, `../database/schema.py` and `make migrate` follow it. A new service's chain is added here |
| `migrate.sh` | Applies the chains to head (or `<chain>=<revision>`), then the first admin when platform's chain ran |
| `first_admin.sh` | The first tenant, Security team and admin, when a first-admin password is set; changes nothing once one exists |
| `healthcheck.py` | `healthcheck.py <url>` or `healthcheck.py db`, standard library only, so images need no curl |
| `service_keys.py` | Which keys each service uses besides its own signing key; every target reads it so no service holds a key it does not use |
| `console-start.mjs` | Swaps the console build's placeholder service URLs for the container's env, then serves it |
| `bake_plugins.py` | Puts the plugins `../plugins.json` pins (full 40-character commits only) into the image's plugins folder |
| `prune_build_cache.sh` | Prunes Docker's build cache past `OPS_BUILD_CACHE_CAP` GB after image builds |

Tests: `bake_plugins.py` is covered by `scripts/tests/test_bake_plugins.py` (`uv run pytest -q scripts/tests/test_bake_plugins.py`);
the rest is proved by the compose and kind proofs (`../compose/proof.sh`, `../k8s/proof.sh`). The `service_keys.py`
docstring names `deploy/k8s/secrets.py`; the file is `../k8s/write_secrets.py`.

Docs: [docs/deploy/compose.md](../../docs/deploy/compose.md), [docs/deploy/install.md](../../docs/deploy/install.md).
