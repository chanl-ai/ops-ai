# Install steps that need Python

`install_api.py` holds the steps of `./install.sh` that need Python, run inside the platform image on the install's
own network, so the host needs no Python: storing the model provider's key in Secrets through the API, checking each
service's schema version, and rendering a DBA-mode upgrade as Alembic's offline SQL. Inputs come from the environment
only; nothing secret is printed. Guide: `docs/deploy/install.md`.

Working here: the script runs only inside an image started by `../../install.sh`, so it is proved by `make install-proof`
(slow; a fresh clone on images pulled from GHCR). Add an input as an `OPS_INSTALL_*` environment value, never an
argument, so no secret reaches a command line. Folder rules: `../CLAUDE.md`.
