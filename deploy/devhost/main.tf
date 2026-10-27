terraform {
  required_version = ">= 1.5.0"
  required_providers {
    coder = {
      source  = "coder/coder"
      version = "~> 2.0"
    }
    docker = {
      source  = "kreuzwerker/docker"
      version = "~> 3.0"
    }
  }
}

variable "docker_socket" {
  default     = ""
  description = "Optional Docker socket URI"
  type        = string
}

# Behind a company package mirror (docs/deploy/install.md, "Behind a company mirror"): the settings every workspace
# gets, as environment names to values, e.g. UV_DEFAULT_INDEX, NPM_CONFIG_REGISTRY, COREPACK_NPM_REGISTRY, OPS_RUNNER_WASM_URL,
# PLAYWRIGHT_DOWNLOAD_HOST, APT_MIRROR. They reach envbuilder (so the image build reads them) and each developer's shell
# (so `make install` installs from the mirror). Push them once:
#   coder templates push ops-ai --directory deploy/devhost --variable 'mirror_settings={"UV_DEFAULT_INDEX":"https://..."}'
variable "mirror_settings" {
  default     = {}
  description = "Package mirror settings, environment name to value"
  type        = map(string)
}

# A registry prefix, ending in a slash, for the third-party images: envbuilder, the Python base image, PostgreSQL, OPA.
variable "base_image_prefix" {
  default     = ""
  description = "Registry prefix for third-party images, e.g. registry.example.com/dockerhub/"
  type        = string
}

provider "coder" {}
provider "docker" {
  host = var.docker_socket != "" ? var.docker_socket : null
}

data "coder_provisioner" "me" {}
data "coder_workspace" "me" {}
data "coder_workspace_owner" "me" {}

data "coder_parameter" "git_url" {
  name         = "git_url"
  display_name = "Git URL"
  description  = "Clone URL for this repository (the one that contains .devcontainer/)"
  type         = "string"
  mutable      = false
  order        = 1
}

data "coder_parameter" "repo_dir" {
  name         = "repo_dir"
  display_name = "Repo directory"
  description  = "Directory name envbuilder clones into under /workspaces"
  type         = "string"
  default      = "ops-ai"
  mutable      = false
  order        = 2
}

data "coder_parameter" "cpu" {
  name         = "cpu"
  display_name = "CPU"
  description  = "CPU limit for the workspace container (cores). Sidecars have their own caps."
  type         = "number"
  default      = "4"
  mutable      = true
  order        = 3
  validation {
    min = 1
    max = 32
  }
}

data "coder_parameter" "memory" {
  name         = "memory"
  display_name = "Memory"
  description  = "Memory limit for the workspace container (GiB). Sidecars have their own caps."
  type         = "number"
  default      = "8"
  mutable      = true
  order        = 4
  validation {
    min = 2
    max = 64
  }
}

data "coder_parameter" "devcontainer_builder" {
  name         = "devcontainer_builder"
  display_name = "Envbuilder image"
  description  = "Image that builds the workspace from the repo's devcontainer.json. Pin a release in production."
  type         = "string"
  default      = "ghcr.io/coder/envbuilder:latest" # var.base_image_prefix is put in front of it
  mutable      = true
  order        = 5
}

locals {
  repo_dir                   = data.coder_parameter.repo_dir.value
  workspace_folder           = "/workspaces/${local.repo_dir}"
  policy_dir                 = "${local.workspace_folder}/services/tools-service/policy"
  git_author_name            = coalesce(data.coder_workspace_owner.me.full_name, data.coder_workspace_owner.me.name)
  git_author_email           = data.coder_workspace_owner.me.email
  devcontainer_builder_image = "${var.base_image_prefix}${data.coder_parameter.devcontainer_builder.value}"
  workspace_memory_bytes     = tonumber(data.coder_parameter.memory.value) * 1024 * 1024 * 1024
  workspace_cpus             = tonumber(data.coder_parameter.cpu.value)
  envbuilder_env = {
    "ENVBUILDER_GIT_URL" : data.coder_parameter.git_url.value,
    "CODER_AGENT_TOKEN" : coder_agent.main.token,
    "CODER_AGENT_URL" : replace(data.coder_workspace.me.access_url, "/localhost|127\\.0\\.0\\.1/", "host.docker.internal"),
    "ENVBUILDER_INIT_SCRIPT" : replace(coder_agent.main.init_script, "/localhost|127\\.0\\.0\\.1/", "host.docker.internal"),
    "ENVBUILDER_FALLBACK_IMAGE" : "${var.base_image_prefix}mcr.microsoft.com/devcontainers/python:1-3.12-bookworm",
    "OPS_INFRA" : "external",
  }
  mirror_env = merge(var.mirror_settings, var.base_image_prefix == "" ? {} : { "OPS_BASE_IMAGE_PREFIX" : var.base_image_prefix })
  docker_env = [for k, v in merge(local.envbuilder_env, local.mirror_env) : "${k}=${v}"]
}

resource "docker_network" "workspace" {
  name = "coder-${data.coder_workspace.me.id}"
}

resource "docker_volume" "workspaces" {
  name = "coder-${data.coder_workspace.me.id}"
  lifecycle {
    ignore_changes = all
  }
  labels {
    label = "coder.workspace_id"
    value = data.coder_workspace.me.id
  }
  labels {
    label = "coder.owner"
    value = data.coder_workspace_owner.me.name
  }
}

resource "docker_volume" "pgdata" {
  name = "coder-${data.coder_workspace.me.id}-pg"
  lifecycle {
    ignore_changes = all
  }
  labels {
    label = "coder.workspace_id"
    value = data.coder_workspace.me.id
  }
}

resource "docker_image" "devcontainer_builder" {
  name         = local.devcontainer_builder_image
  keep_locally = true
}

resource "coder_agent" "main" {
  arch = data.coder_provisioner.me.arch
  os   = "linux"
  dir  = local.workspace_folder
  env = merge(local.mirror_env, {
    GIT_AUTHOR_NAME     = local.git_author_name
    GIT_AUTHOR_EMAIL    = local.git_author_email
    GIT_COMMITTER_NAME  = local.git_author_name
    GIT_COMMITTER_EMAIL = local.git_author_email
    OPS_INFRA           = "external"
  })
  startup_script = <<-EOT
    set -e
    if [ ! -f "${local.workspace_folder}/.devcontainer/.env.local" ] && [ -f "${local.workspace_folder}/.devcontainer/.env.local.example" ]; then
      cp "${local.workspace_folder}/.devcontainer/.env.local.example" "${local.workspace_folder}/.devcontainer/.env.local"
    fi
  EOT
}

resource "docker_container" "workspace" {
  count       = data.coder_workspace.me.start_count
  image       = docker_image.devcontainer_builder.image_id
  name        = "coder-${data.coder_workspace_owner.me.name}-${lower(data.coder_workspace.me.name)}"
  hostname    = data.coder_workspace.me.name
  env         = local.docker_env
  memory      = local.workspace_memory_bytes
  cpus        = local.workspace_cpus
  memory_swap = local.workspace_memory_bytes
  networks_advanced {
    name = docker_network.workspace.name
  }
  host {
    host = "host.docker.internal"
    ip   = "host-gateway"
  }
  volumes {
    container_path = "/workspaces"
    volume_name    = docker_volume.workspaces.name
    read_only      = false
  }
  labels {
    label = "coder.workspace_id"
    value = data.coder_workspace.me.id
  }
}

# Same images and settings as deploy/compose/compose.yaml. Envbuilder does not start compose services.
resource "docker_container" "postgres" {
  count       = data.coder_workspace.me.start_count
  image       = "${var.base_image_prefix}postgres:17-alpine"
  name        = "coder-${data.coder_workspace.me.id}-postgres"
  memory      = 2 * 1024 * 1024 * 1024
  cpus        = 1
  memory_swap = 2 * 1024 * 1024 * 1024
  restart     = "unless-stopped"
  env = [
    "POSTGRES_USER=ops",
    "POSTGRES_PASSWORD=ops",
    "POSTGRES_DB=ops_runtime",
  ]
  networks_advanced {
    name    = docker_network.workspace.name
    aliases = ["postgres"]
  }
  volumes {
    volume_name    = docker_volume.pgdata.name
    container_path = "/var/lib/postgresql/data"
  }
  healthcheck {
    test     = ["CMD-SHELL", "pg_isready -U ops -d ops_runtime"]
    interval = "2s"
    timeout  = "3s"
    retries  = 30
  }
}

resource "docker_container" "opa" {
  count       = data.coder_workspace.me.start_count
  image       = "${var.base_image_prefix}openpolicyagent/opa:1.21.1"
  name        = "coder-${data.coder_workspace.me.id}-opa"
  memory      = 512 * 1024 * 1024
  cpus        = 1
  memory_swap = 512 * 1024 * 1024
  restart     = "unless-stopped"
  command     = ["run", "--server", "--watch", "--addr", "0.0.0.0:8181", "--log-level", "error", local.policy_dir]
  networks_advanced {
    name    = docker_network.workspace.name
    aliases = ["opa"]
  }
  volumes {
    volume_name    = docker_volume.workspaces.name
    container_path = "/workspaces"
    read_only      = true
  }
}

resource "docker_container" "greenmail" {
  count       = data.coder_workspace.me.start_count
  image       = "${var.base_image_prefix}greenmail/standalone:2.1.3"
  name        = "coder-${data.coder_workspace.me.id}-greenmail"
  memory      = 512 * 1024 * 1024
  cpus        = 1
  memory_swap = 512 * 1024 * 1024
  restart     = "unless-stopped"
  env = [
    "GREENMAIL_OPTS=-Dgreenmail.setup.test.smtp -Dgreenmail.setup.test.imap -Dgreenmail.hostname=0.0.0.0 -Dgreenmail.auth.disabled",
  ]
  networks_advanced {
    name    = docker_network.workspace.name
    aliases = ["greenmail"]
  }
}

resource "docker_container" "mailpit" {
  count       = data.coder_workspace.me.start_count
  image       = "${var.base_image_prefix}axllent/mailpit:v1.27"
  name        = "coder-${data.coder_workspace.me.id}-mailpit"
  memory      = 512 * 1024 * 1024
  cpus        = 1
  memory_swap = 512 * 1024 * 1024
  restart     = "unless-stopped"
  env = [
    "MP_SMTP_AUTH_ACCEPT_ANY=1",
    "MP_SMTP_AUTH_ALLOW_INSECURE=1",
  ]
  networks_advanced {
    name    = docker_network.workspace.name
    aliases = ["mailpit"]
  }
}

resource "coder_app" "console" {
  count        = data.coder_workspace.me.start_count
  agent_id     = coder_agent.main.id
  slug         = "console"
  display_name = "Console"
  url          = "http://localhost:3016"
  share        = "owner"
}

resource "coder_app" "mailpit" {
  count        = data.coder_workspace.me.start_count
  agent_id     = coder_agent.main.id
  slug         = "mailpit"
  display_name = "Mailpit"
  url          = "http://mailpit:8025"
  share        = "owner"
}

module "code-server" {
  count    = data.coder_workspace.me.start_count
  source   = "registry.coder.com/coder/code-server/coder"
  version  = "~> 1.0"
  agent_id = coder_agent.main.id
  order    = 1
}
