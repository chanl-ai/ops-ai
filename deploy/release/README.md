# Release package

One versioned package a client team installs on its own Linux machines with Docker, with no checkout. Runbook:
`docs/deploy/release-package.md`; the guide inside the package: `docs/deploy/install-guide.md`.

| File | Role |
|---|---|
| `package.sh` | `make release-package TAG=<ref>`: builds every image for linux/amd64 from `git archive`, saves them as one bundle, and writes the package (compose files, env template, db/postgres, db/azure-sql, INSTALL.md, images.txt), its tarball and checksums under `dist/` |
| `proof.sh` | `make release-proof PACKAGE=dist/ops-ai-<version>.tar.gz`: installs from the tarball alone as a client would, against a PostgreSQL with TLS and an admin that is not a superuser, and walks every console page |
