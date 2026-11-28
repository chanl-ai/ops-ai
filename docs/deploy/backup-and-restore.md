# Back up and restore an install

Status: current.

If a disk fails, a change goes wrong or someone deletes the wrong thing, you recover by restoring a backup. An Ops AI install
keeps its state in three places: the database, the stored files and knowledge bytes, and the settings file with its keys.
Your backup has to cover all three, and a restore needs the same secrets key that the backup was made with. The script's
backup and restore have been run end to end on one machine, and rows and files made after a backup were gone after its
restore.

## Back up and restore with the script

```bash
./install.sh backup
./install.sh restore backups/<file>.tar.gz
```

A backup is one archive in `./backups/`, readable only by its owner. It holds a dump of the database, the files and
knowledge volumes, and `ops-ai.env`. `--out DIR` writes it to another folder. A restore stops the services, recreates the
database from the dump, puts the volumes back, starts everything and runs the install check. It refuses a backup that
was made with another secrets key.

In `dba` mode both commands need `--admin-url-file <file>`, because the services' own logins cannot dump the database
under its tenant policies.

> [!IMPORTANT]
> A backup holds `ops-ai.env` and its keys, in clear text inside the archive. Keep it as safe as the database.
> `OPS_SECRETS_KEY` unlocks every stored credential, and without it a restored install cannot call your systems.

## Back up and restore by hand

Back up the database as the server admin, with your usual PostgreSQL tools or, on Azure, with automated backups and
point-in-time restore. A dump taken as the schema owner stops with a row-level security error, because the tenant
policies apply to the owner too.

```bash
docker run --rm -e PGPASSWORD=<admin password> -v "$PWD/backup:/backup" postgres:17 \
  pg_dump -Fc -f /backup/ops.dump "host=<host> port=5432 user=<admin> dbname=ops sslmode=require"
docker run --rm -v ops-ai_files-data:/data -v "$PWD/backup:/out" alpine tar czf /out/files-data.tgz -C /data .
docker run --rm -v ops-ai_kb-data:/data -v "$PWD/backup:/out" alpine tar czf /out/kb-data.tgz -C /data .
```

Keep a copy of the settings file, or at least `OPS_SECRETS_KEY`, with each backup.

To restore into a new database, stop the services and then run:

```bash
psql -v ON_ERROR_STOP=1 "host=<host> port=5432 user=<admin> dbname=postgres sslmode=require" \
  -c "CREATE DATABASE ops_restored OWNER ops_migrator"
docker run --rm -e PGPASSWORD=<admin password> -v "$PWD/backup:/backup" postgres:17 \
  pg_restore --exit-on-error -d "host=<host> port=5432 user=<admin> dbname=ops_restored sslmode=require" /backup/ops.dump
docker run --rm -v ops-ai_files-data:/data -v "$PWD/backup:/in" alpine sh -c "rm -rf /data/* && tar xzf /in/files-data.tgz -C /data"
docker run --rm -v ops-ai_kb-data:/data -v "$PWD/backup:/in" alpine sh -c "rm -rf /data/* && tar xzf /in/kb-data.tgz -C /data"
```

Point each service's database setting in `ops-ai.env` at `ops_restored`, keep the same keys in the settings file, and start everything
again. The two `rm -rf` commands above empty each volume before they restore it, so run them only against the volumes you mean to replace. Then run `./install.sh status` to run the install check.

## What to back up where

| Install | Database | Files and knowledge bytes |
|---|---|---|
| Script or Compose | `pg_dump` as the server admin | The `files-data` and `kb-data` volumes |
| Kubernetes | `pg_dump` as the server admin | Volume snapshots of the files and kb claims |
| Files in S3 or Azure Blob | As above | The store's own versioning or replication |

## Limits

- Ops AI schedules no backups. Run the script from your scheduler, or rely on your database's own backups plus copies of
  the volumes and the settings file.
