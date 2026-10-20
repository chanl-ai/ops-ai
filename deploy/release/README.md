# Release package

One versioned package a client team installs on its own Linux machines with Docker, with no checkout. Runbook:
`docs/deploy/release-package.md`; the guide inside the package: `docs/deploy/install-guide.md`.

| File | Role |
|---|---|
| `package.sh` | `make release-package TAG=<ref>`: builds every image for linux/amd64 from `git archive`, saves them as one bundle, and writes the package (compose files, env template, db/postgres, db/azure-sql, INSTALL.md, images.txt), its tarball and checksums under `dist/` |
| `proof.sh` | `make release-proof PACKAGE=dist/ops-ai-<version>.tar.gz`: installs from the tarball alone as a client would, against a PostgreSQL with TLS and an admin that is not a superuser, and walks every console page |
| `version` | The image version a checkout installs (`./install.sh`) and the release workflow publishes by default |
| `images.sh` | Builds every image from one commit (`git archive`) for the platforms given, loads or pushes them, with the OCI labels; used by `package.sh`, `install.sh --build` and `.github/workflows/release-images.yml` |
| `install_proof.sh` | `make install-proof`: a fresh clone, `./install.sh` unattended on images pulled from GHCR, every console page, rerun, upgrade, backup, restore, a failed upgrade rolled back, and DBA mode (`docs/deploy/install.md`) |
