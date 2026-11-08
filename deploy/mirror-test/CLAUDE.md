# Mirror test lane

Status: current.

The behind-a-company-mirror lane: a clean install of both lockfiles through a local Nexus on a network with no other
way out, a fast test subset, then the dependency age, vulnerability and licence checks. It runs in its own compose
project (`ops-mirror-test`) and never touches the dev stack. Deploy-wide rules: [../CLAUDE.md](../CLAUDE.md).

| File | Role |
|---|---|
| `lane.sh` | `make qa-mirror` runs the lane; `make mirror-down` (`lane.sh down`) stops Nexus and deletes its cache; `MIRROR_KEEP_UP=1` leaves Nexus up |
| `compose.yaml` | Nexus and the installer container on a closed network |
| `installer.Dockerfile`, `inside.sh` | The install container and the steps run inside it; the first step proves a download that skips the mirror fails |
| `nexus.sh` | Sets up the PyPI and npm proxies and blocks paths, to test what a mirror refuses |
| `audit-baseline.txt` | Accepted findings of the vulnerability and licence checks |

The lane is slow (a full install from an empty cache). The settings a real mirror needs are in
[docs/deploy/install.md](../../docs/deploy/install.md), "Behind a company mirror"; the related `make deps-doctor`,
`deps-relock MIRROR=1` and `install-mirror` targets are in `make/deps.mk`.
