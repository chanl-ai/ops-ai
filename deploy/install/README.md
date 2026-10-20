# Install steps that need Python

`install_api.py` holds the steps of `./install.sh` that need Python, run inside the platform image on the install's
own network, so the host needs no Python: storing the model provider's key in Secrets through the API, checking each
service's schema version, and rendering a DBA-mode upgrade as Alembic's offline SQL. Inputs come from the environment
only; nothing secret is printed. Guide: `docs/deploy/install.md`.
