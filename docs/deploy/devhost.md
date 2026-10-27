# Shared development host

Status: current.

Each developer on a shared machine works in their own container. Their code, database, settings and keys stay out of
the others' way. They open a workspace in the browser; they never log in to the machine itself.

The same definition runs on a laptop (VS Code or Cursor), in Codespaces, under DevPod, and under Coder on a shared
host. Infra (PostgreSQL, OPA, the test mail servers) runs as side containers next to the workspace. There is no Docker
inside the workspace.

| Path | What it is |
|---|---|
| `.devcontainer/devcontainer.json` | Workspace image, Node and pnpm pins, forwarded console and Mailpit ports, `OPS_INFRA=external` |
| `.devcontainer/compose.yaml` | Includes `deploy/compose/compose.yaml` and adds the workspace service; each checkout is its own compose project |
| `.devcontainer/.env.local.example` | Names the provider keys; copy to `.env.local` (gitignored) and fill in |
| `deploy/devhost/` | Coder template (Terraform, Docker provider, envbuilder) |

## What separates developers, and what does not

| Apart | Shared |
|---|---|
| Containers, compose project, network and volumes | The VM's Docker engine |
| Provider keys in `.devcontainer/.env.local` | Whoever administers Docker on the VM can list, inspect and exec into every container |
| No host shell: Coder is the only way in | CPU and memory on the VM as a whole |

## Laptop, Codespaces, DevPod

Open this repository in a tool that reads `.devcontainer/`. After create: `make up OPS_INFRA=external`. Console is
port 3016; Mailpit's web page is 8025. Two checkouts need different folder names so compose project names do not collide.

## Coder on an Ubuntu VM

Copy-pasteable from a clean Ubuntu machine. Docker and Coder run on the host; developers never SSH in.

```bash
# Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
# log out and back in so the group applies, or: newgrp docker

# Coder (open source)
curl -fsSL https://coder.com/install.sh | sh
sudo systemctl enable --now coder

# This repository, then the template
git clone <this-repo-url> ops-ai && cd ops-ai
coder login http://127.0.0.1:3000
coder templates push ops-ai --directory deploy/devhost -y

# A developer (repeat per person)
coder users create --username dev1 --email dev1@example.com --login-type password
```

Open the Coder UI, create a workspace from the `ops-ai` template, set the Git URL to this repository, and choose CPU
and memory. Envbuilder builds from `.devcontainer/devcontainer.json`. Sidecar containers use the same images as
`deploy/compose/compose.yaml` on a private network. Copy `.devcontainer/.env.local.example` to `.env.local` and put
this developer's keys there.

Inside the workspace: `make up OPS_INFRA=external`.
