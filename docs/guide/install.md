# Install

Status: current.

<!-- The steps below are included from docs/deploy/install.md, the install script's guide, when the page and
INSTALL.md are built; edit them there. -->

One script installs Ops AI on a machine with Docker from a clone of the repository, asks a few questions, checks the
result, and later upgrades, backs up, restores and reports on the same install ([Operate](operate.md)). It pulls the
published images by default; a release's offline image file, or a build from source, serves a machine with no
registry access.

The published images are at `ghcr.io/chanl-ai/ops-ai`.

## Before you start

| Item | What you need | Details |
|---|---|---|
| A host | One Linux machine with Docker Engine 24 or newer, Docker Compose 2.22 or newer, curl and tar, 4 GB of memory for the containers and 15 GB of free disk | [Sizing](deployment-options.md#sizing) |
| A DNS name and TLS | A name such as `ops.example.com` on your load balancer or reverse proxy, forwarding to the port the script asks for | [The network](deployment-options.md#the-network) |
| PostgreSQL | For a trial, the script's built-in database. For real use, your own PostgreSQL 15 or newer: either a login that may change the schema, or DBA mode, where your DBA applies the scripts the install writes | [Data and database](data-and-database.md) |
| A model endpoint | Any OpenAI-compatible endpoint and its key; the built-in test model will do for a first look | [Models](models.md) |
| The first admin | A name and email address for the person who signs in first and invites everyone else | |
| Sign-in and outbound hosts | Your identity provider's OIDC or SAML details, and the hosts Ops AI will call, for the Security admin to set after the install | [Security and governance](security-and-governance.md) |

<!-- guide: include from "## Install" until "## Appendix: by hand" -->
The install steps, the questions the script asks and its other commands are in [Install Ops AI with install.sh](../deploy/install.md).

## By hand

Every step the script runs can also be run by hand: the Compose files and settings in
[Ops AI on Docker Compose](../deploy/compose.md), the DBA's scripts in
[The database](../deploy/database.md), and a Kubernetes install in [Ops AI on Kubernetes](../deploy/kubernetes.md).

## Install behind a company mirror or offline

The `opsai` command line (package `ops-ai`, `sdk/python`) needs Python 3.11 or newer and two packages, `httpx` and
`typing-extensions`, plus their small dependencies. It does not need the repository's developer workspace, so it does
not need the packages `make install` pulls in for contributors (`datamodel-code-generator`, `pyright`, `moto` and
others), some of which a mirror may not serve. `make install` is for contributors who run the services and the full
test suite; to use the command, run `make install-cli`.

```
make install-cli          # uv tool install ./sdk/python, or pip install --user when uv is missing
opsai --help                # prints "usage: ops [-h] area ..."
```

`make chat` and the other targets in `make/cli.mk` run the `ops` on your PATH, then `.venv/bin/ops` when the workspace
is installed. When neither exists they print `make: the opsai command is not installed; run 'make install-cli' ...` and
stop; they never sync the workspace.

The command is called `opsai`. `ops` is a common name, so the package keeps an `ops` command for one release only,
and it prints a note that `opsai` is the name. `make install-cli` installs `ops` only when no other tool called `ops` is
on PATH, and prints which it did.

### Sonatype Nexus

Create or choose a PyPI group or proxy repository. Its index is
`https://<nexus-host>/repository/<repo-name>/simple/` (the trailing `/simple/` matters; the repository's own address
is not an index). Set it for the installer you use. `make install-cli` reads either set of names and translates the pip
names for uv, so one set is enough.

| Setting | For | Notes |
|---|---|---|
| `UV_DEFAULT_INDEX` (or `UV_INDEX_URL`) | uv | The index replaces PyPI |
| `PIP_INDEX_URL` | pip, and uv when no `UV_*` index is set | `PIP_EXTRA_INDEX_URL` adds a second index |
| `PIP_TRUSTED_HOST` / `UV_INSECURE_HOST` | a host without valid TLS | Prefer a CA bundle below |
| `SSL_CERT_FILE` (also `PIP_CERT`) | a company CA certificate, PEM file | `UV_NATIVE_TLS=1` makes uv use the operating system's certificate store instead |

```
export UV_DEFAULT_INDEX=https://nexus.example.com/repository/pypi-group/simple/
export SSL_CERT_FILE=/etc/ssl/company-ca.pem
make install-cli
opsai --help
```

The installer runs uv from outside the repository, so the repository's `[tool.uv]` settings are not read (its
`exclude-newer` needs upload times, which Nexus's PyPI proxy does not send, so every version would look too new). Your
own `uv.toml` (index, credentials, certificates) is read.

Credentials stay out of URLs in shared files, because a URL with a password appears in logs, `ps` and shell history.
Use one of:

- uv: name the index and give the credentials in the environment, with the name in capitals:
  `UV_DEFAULT_INDEX=nexus=https://nexus.example.com/repository/pypi-group/simple/`,
  `UV_INDEX_NEXUS_USERNAME=<user>`, `UV_INDEX_NEXUS_PASSWORD=<password or token>`.
- A `~/.netrc` file (`machine nexus.example.com login <user> password <token>`, mode 600), which uv and pip both read.
- pip: `pip install keyring` and store the password there (`keyring set https://nexus.example.com <user>`), then
  `pip` asks keyring for it.

### What the Nexus admin may need to allow

If Nexus Firewall or an IQ policy blocks packages, `make install-cli` needs exactly these, at any version that meets the
range. The versions in the second column are the newest at the time of writing and the ones the offline proof ran with;
a version a policy holds back for being new can be replaced by an older one, down to the range's lower bound.

| Package | Version range the CLI accepts | Newest tested |
|---|---|---|
| httpx | 0.27 up to, not including, 1.0 | 0.28.1 |
| typing-extensions | 4.12 or newer | 4.16.0 |
| httpcore | any that httpx accepts (1.x) | 1.0.9 |
| h11 | 0.16 or the range httpcore names | 0.16.0 |
| anyio | any that httpx accepts (4.x) | 4.16.0 |
| idna | any that anyio and httpx accept | 3.20 |
| certifi | any | 2026.10.23 |

Installing from a checkout (`make install-cli` without `WHEELS`) also builds the package, which downloads the build tool
and its own dependencies: `hatchling`, `packaging`, `pathspec`, `pluggy`, `trove-classifiers`. The wheelhouse below
carries a built wheel, so it needs none of these on the machine that installs.

### Offline: a wheelhouse

On a machine with internet, write every wheel the command needs into `dist/wheelhouse/`, with a `requirements.txt`
that pins them:

```
make wheelhouse                                   # macOS arm64 and x86_64, Linux x86_64, Windows; Python 3.11 and 3.12
make wheelhouse PLATFORMS='manylinux2014_x86_64' PYTHONS='3.12'      # a narrower set
```

Copy the folder to the target machine (a share, a USB drive, an archive) and install without any network:

```
make install-cli WHEELS=dist/wheelhouse           # uv tool install --no-index --find-links, or pip --no-index
opsai --help
```

The installer needs `uv` or `pip` on the target machine; `uv` is not part of the wheelhouse.

As an alternative to copying the folder, upload the wheels to a Nexus hosted PyPI repository and install from it as
above. Create the hosted repository (format `pypi`, type `hosted`), add it to the group the developers use, and upload:

```
python -m pip install twine
twine upload --repository-url https://nexus.example.com/repository/pypi-hosted/ \
  -u <user> -p "$NEXUS_PASSWORD" dist/wheelhouse/*.whl
```

Install from it by naming the package instead of building the checkout (the hosted repository holds the wheels, not the
build tool, so building from the checkout would need the proxy):

```
export UV_DEFAULT_INDEX=https://nexus.example.com/repository/pypi-hosted/simple/
make install-cli FROM_INDEX=1
```

Use an account that may write to the repository, and take the password from the environment or `~/.pypirc`, not a
shared file. Upload `ops_ai-*.whl` and the dependency wheels; Nexus ignores files it already has unless the repository's
deployment policy forbids redeploys.

### Check the result

```
opsai --help                # lists the areas (chat, kb, apps, ...) when the command is installed
command -v opsai          # where the tool environment put it
```

If `opsai` is not found after the install, the tool folder is not on PATH: run `uv tool update-shell` and open a new
shell, or add `~/.local/bin` (pip --user on Linux and macOS) to PATH.

### Rerun the Nexus proof

`make nexus-proof` starts Sonatype Nexus Repository (Docker image `sonatype/nexus3`), makes a PyPI proxy, a hosted and a
group repository through its REST API, installs the command from the group in a `python:3.12-slim` container that can
reach only Nexus, then uploads a wheelhouse to the hosted repository with twine and installs from it with the proxy
turned off. It removes the containers when it ends. It needs Docker, about 3 GB of memory and a few minutes for Nexus to
start.
