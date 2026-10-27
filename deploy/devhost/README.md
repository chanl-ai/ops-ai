# Shared dev host

Coder template: one workspace per developer from this repo's `.devcontainer/`, built with envbuilder.
Side containers (PostgreSQL, OPA, GreenMail, Mailpit) use the same images as `deploy/compose/compose.yaml`.

Developers never use the VM's shell. Each has their own containers, network, volumes and keys.
Whoever administers Docker on the VM can see every container.

Behind a company package mirror, push the template with `--variable 'mirror_settings={"UV_DEFAULT_INDEX":"https://...","NPM_CONFIG_REGISTRY":"https://..."}'` and `--variable base_image_prefix=registry.example.com/dockerhub/`; every workspace then builds and installs through it with no edits (`docs/deploy/install.md`, "Behind a company mirror").

Install (Ubuntu), add this template, create a user, open a workspace: `docs/deploy/devhost.md`.

```bash
curl -fsSL https://get.docker.com | sudo sh
curl -fsSL https://coder.com/install.sh | sh
sudo systemctl enable --now coder
coder login http://127.0.0.1:3000
coder templates push ops-ai --directory deploy/devhost -y
coder users create --username dev1 --email dev1@example.com --login-type password
```
