# Install the command line

Status: current. The package is not on the public Python index yet: install it from a clone, or from the wheel your
operator gives you. Publishing it is planned.

**Script your team's agents, workflows, knowledge, apps and tasks from a terminal, and keep them in version control.**

## Clicking does not scale to a team

A console is the right place to look at a run. It is the wrong place to keep forty agent definitions, apply the same
change to staging and production, or let a pipeline publish after a review. Without a command line, every change is a
sequence of clicks that nobody can diff, repeat or hand to a colleague, and the definitions live only in the database.

The opsai command line works against an Ops AI install that someone else runs. It installs on its own, without the
platform, and needs only Python 3.11 or newer and two small packages, so it also installs through a company package
mirror or with no network at all. The steps below install it, sign in and check it.

## Install

From a clone of the repository, with uv or pip:

```bash
uv tool install ./sdk/python             # or: python -m pip install --user ./sdk/python
opsai --help                             # prints "usage: opsai ..." and the areas
```

From a wheel your operator built, or a company index that holds it:

```bash
uv tool install ops-ai                   # or: python -m pip install --user ops-ai
```

The package is `ops-ai` and the command is `opsai`. The package also installs an `ops` command for one release, which
prints that `opsai` is the new name.

If `opsai` is not found after the install, its folder is not on your PATH: run `uv tool update-shell` and open a new
shell, or add `~/.local/bin` (pip on Linux and macOS) to PATH.

## Sign in

```bash
opsai login --base-url https://ops.example.com --email you@example.com
opsai people me
```

`opsai login` asks for your password and saves the address, your team and the session in a profile, which every later
command and the Python client read. The session renews itself. No token is printed.

| Setting | What it does | Default |
|---|---|---|
| `--profile NAME` or `OPS_PROFILE` | Keeps several sign-ins side by side, such as staging and production | `default` |
| `OPS_BASE_URL` | The Ops AI address, when no profile holds one | none |
| `OPS_CONFIG` | Reads profiles from another file | the profile file in your home folder |
| `--team ID` | Acts in another of your teams | the team saved at sign-in |
| `--json` | Prints JSON instead of a table, on every command | off |

## Through a company mirror

Point uv or pip at your mirror's Python index. For Sonatype Nexus the index is
`https://<nexus-host>/repository/<repo-name>/simple/`; the trailing `/simple/` matters.

| Setting | For | Notes |
|---|---|---|
| `UV_DEFAULT_INDEX` (or `UV_INDEX_URL`) | uv | Replaces the public index |
| `PIP_INDEX_URL` | pip | `PIP_EXTRA_INDEX_URL` adds a second index |
| `SSL_CERT_FILE` (also `PIP_CERT`) | A company CA certificate, as a PEM file | `UV_NATIVE_TLS=1` makes uv use the operating system's certificates instead |
| `PIP_TRUSTED_HOST` / `UV_INSECURE_HOST` | A host without valid TLS | Prefer a CA certificate |

```bash
export UV_DEFAULT_INDEX=https://nexus.example.com/repository/pypi-group/simple/
export SSL_CERT_FILE=/etc/ssl/company-ca.pem
uv tool install ./sdk/python
```

Keep credentials out of URLs in shared files, because a URL with a password shows up in logs and shell history. Use a
`~/.netrc` file (`machine nexus.example.com login <user> password <token>`, mode 600), which uv and pip both read, or
uv's `UV_INDEX_<NAME>_USERNAME` and `UV_INDEX_<NAME>_PASSWORD` with a named index.

If a firewall policy on the mirror blocks packages, these are the ones the command line needs, at any version in range:

| Package | Versions accepted | Newest tested |
|---|---|---|
| httpx | 0.27 up to, not including, 1.0 | 0.28.1 |
| typing-extensions | 4.12 or newer | 4.16.0 |
| httpcore | any that httpx accepts (1.x) | 1.0.9 |
| h11 | any that httpcore accepts | 0.16.0 |
| anyio | any that httpx accepts (4.x) | 4.16.0 |
| idna | any that anyio and httpx accept | 3.20 |
| certifi | any | 2026.10.23 |

Installing from a clone also builds the package, which needs `hatchling`, `packaging`, `pathspec`, `pluggy` and
`trove-classifiers` from the mirror. Installing a built wheel needs none of them.

## With no network

On a machine with internet, put the wheel and its dependencies in one folder:

```bash
python -m pip wheel --no-deps --wheel-dir wheelhouse ./sdk/python
python -m pip download --dest wheelhouse httpx typing-extensions
```

Copy the folder to the target machine and install from it alone:

```bash
uv tool install --no-index --find-links wheelhouse ops-ai     # or: python -m pip install --user --no-index --find-links wheelhouse ops-ai
opsai --help
```

To build the folder for other operating systems or Python versions than the one you are on, or to upload it to a Nexus
hosted repository, see [Install from a company registry](../deploy/install.md#install-from-a-company-registry).

## What success looks like

`opsai --help` prints the areas, and `opsai people me` prints you and your team. From then on a definition is a file:
validate it, apply it, and review the change in your repository like any other.

## Next

<!-- site: cards -->
- **[Quickstart](quickstart.md)**: build and run a first workflow with the command line.
- **[Build an agent](use-cases/build-an-agent.md)**: write, test and publish an agent from a file.
- **[Agents](agents.md)**: the agent commands.
- **[Workflows](workflows.md)**: the workflow commands.
