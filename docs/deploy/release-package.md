# Install offline from a release package

Status: current. Proven end to end on a machine that holds only the package; not yet installed on a client's machines.

Install Ops AI on machines with no internet access, where your DBA applies every schema change. A release package is
one download with everything that needs: the images, the Compose files, a settings template, the database scripts and
an install guide. Nothing in it needs the source repository.

## What is in a package

| File | What it holds |
|---|---|
| `ops-ai-<version>.tar.gz` | The folder below as one file |
| `ops-ai-<version>-images.tar.gz` | Every image for linux/amd64, for `docker load` |
| `ops-ai-<version>.SHA256SUMS` | The checksums of both archives |

| Inside the folder | What it holds |
|---|---|
| `INSTALL.md` | The install and operate guide |
| `compose/` | The Compose files: the app, DBA mode, and a trial with a database and test model |
| `ops-ai.env.example` | The settings template with the image names filled in |
| `db/postgres/` | The PostgreSQL scripts for your DBA ([Database](database.md)) |
| `db/azure-sql/` | The SQL Server and Azure SQL scripts, for review ([Azure SQL](../guide/azure-sql.md)) |
| `images.txt`, `release.txt`, `SHA256SUMS` | Each image's name, id, platform and size; the release; every file's checksum |

## Install from it

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

3. **Install the database** with your DBA from `db/postgres/` ([Database](database.md)).
4. **Start it** with the Compose files, in DBA mode ([Docker Compose](compose.md)), and connect a model.

From a clone of the repository, the install script takes the image file instead of pulling:
`./install.sh --offline ops-ai-<version>-images.tar.gz` ([Install with the script](install.md)).

## Get a package

The package is built from a release tag and handed to you by your Ops AI contact. To build one yourself from a clone,
on a machine with Docker:

```bash
make release-package TAG=v1.0.0
```

It builds every image from the tag alone, so uncommitted files never reach a package, and writes the three files above
under `dist/`.

## Limits

- Images are linux/amd64 only in the package; the registry images also come for linux/arm64.
- The install script is not in the package; from the package, install with Compose.
- Some console screens still name a sample bank; taking the name from a setting is planned.
- Installing against a real Azure Database for PostgreSQL server is not yet recorded; the proof uses a server whose
  admin has the same rights.
