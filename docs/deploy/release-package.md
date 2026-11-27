# Install offline from a release package

Status: current.

Some of your machines may have no internet access, or your change process may not allow images to be pulled from a
public registry. A release package is built for that situation. It is a single download with everything an install
needs: the images, the Compose files, a settings template, the database scripts and an install guide. None of it
depends on the source repository. Because your DBA applies every schema change from the package's scripts, the running
containers never need a login that can alter the database. The package has been proven end to end on a machine that
holds nothing else, and has not yet been installed on a client's own machines.

## What is in a package

The package is three files:

| File | What it holds |
|---|---|
| `ops-ai-<version>.tar.gz` | The folder below as one file |
| `ops-ai-<version>-images.tar.gz` | Every image for linux/amd64, for `docker load` |
| `ops-ai-<version>.SHA256SUMS` | The checksums of both archives |

Inside the folder:

| Path | What it holds |
|---|---|
| `INSTALL.md` | The install steps that work from this folder alone, then how to operate it |
| `compose/` | The Compose files: the app, DBA mode, and a trial with a database and a test model |
| `ops-ai.env.example` | The settings template with the image names filled in |
| `db/postgres/` | The PostgreSQL scripts for your DBA ([Database](database.md)) |
| `db/azure-sql/` | The SQL Server and Azure SQL scripts, for review ([Azure SQL](../guide/azure-sql.md)) |
| `images.txt`, `release.txt`, `SHA256SUMS` | Each image's name, id, platform and size, then the release, then every file's checksum |

## Install from the package

<!-- site: steps -->
1. **Check the download** and unpack it.

   ```bash
   shasum -a 256 -c ops-ai-<version>.SHA256SUMS
   tar xzf ops-ai-<version>.tar.gz
   ```

2. **Load the images**, or push them to your own registry and set `OPS_IMAGE_PREFIX` in the settings file.

   ```bash
   docker load -i ops-ai-<version>-images.tar.gz
   ```

3. **Install the database** with your DBA, from `db/postgres/` ([Database](database.md)).
4. **Start it.** Copy `ops-ai.env.example` to `ops-ai.env`, generate the keys and set the seven `OPS_DATABASE_URL_<SERVICE>`
   lines as `INSTALL.md` describes, then run the following from the package folder. Connect a model as in
   [Connect a model](compose.md#connect-a-model), using `compose/` wherever that page says `deploy/compose/`.

   ```bash
   docker compose -p ops-ai -f compose/app.yaml -f compose/dba.yaml --env-file ops-ai.env up -d
   ```

From a clone of the repository, the install script takes the image file instead of pulling:
`./install.sh --offline ops-ai-<version>-images.tar.gz` ([Install with the script](install.md)).

## What success looks like

After step 4, the status command in `INSTALL.md` lists every service as running, and the `agents` service turns healthy
once a model is connected. The first admin signs in at your address.

## Get a package

Your Ops AI contact hands you the package for a release. To build one yourself, on a machine with Docker, `uv` and a
clone of the repository:

```bash
make release-package TAG=v1.2.0
```

The build reads only what the tag contains, so files you have not committed cannot end up in a package. It writes the
three files above under `dist/`. For a release tag, the file names carry the version exactly as you typed it, such as
`v1.2.0`, and the images inside the package carry the same tag. The images in the registry drop the `v`, so an install
from the registry uses `1.2.0`.

## Limits

- The package's images are for linux/amd64 only. The registry images also come for linux/arm64.
- The install script is not in the package. `INSTALL.md` installs with Compose and your DBA's scripts.
- The Compose files mount a plugins folder from two levels above `compose/`, which is outside the package. Set
  `OPS_PLUGINS_HOST_DIR` in the settings file to a folder you own, even an empty one.
- A package does not carry upgrade scripts for the database. For the move to a new release, your DBA gets them from a
  clone with `make db-upgrade-sql` ([Database](database.md#upgrade)).
- Some console screens still name a sample bank. Taking the name from a setting is planned.
- Installing against a real Azure Database for PostgreSQL server has not been recorded. The end-to-end test uses a
  server whose admin has the same rights.
