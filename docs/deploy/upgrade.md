# Upgrade

Status: current. The script's upgrade, rollback on a failed check and same-version rerun are proven on one machine. An
upgrade across two releases that change the schema has not run yet: 1.0.0 is the first release.

Move an install to a new release without losing work. The database moves first, then the services; a run waiting for a
person resumes on the new release with the workflow or agent version it started on.

## Upgrade with the script

```bash
git fetch --tags && git checkout v<new version>
./install.sh upgrade
```

The script backs up, gets the new images, applies the schema, restarts, and checks. If the check fails, it restores the
backup on the old version and exits with an error. At the version already running, it checks and changes nothing.
`--version V` picks a version other than the checkout's.

In `dba` mode it writes the upgrade scripts to `./dba/upgrade-<from>-to-<to>/`, waits for your DBA to apply them, and
needs `--admin-url-file <file>` to take the backup.

## Upgrade by hand

<!-- site: steps -->
1. **Back up** the database and the stored files ([Back up and restore](backup-and-restore.md)).
2. **Upgrade the database.** Your DBA applies the new release's `upgrade-roles.sql`, then `upgrade.sql` as the schema
   owner, then the new release's `grants.sql` ([Database](database.md#upgrade)).
3. **Start the new images.**

| Install | Command |
|---|---|
| Compose | Set `OPS_IMAGE_TAG` to the new version, then `docker compose -p ops-ai -f deploy/compose/app.yaml --env-file ops-ai.env up -d` (add `-f deploy/compose/dba.yaml` in DBA mode). Without a DBA, the schema job applies the upgrade before the services start |
| Kubernetes | Set the new tag in the overlay, then `kubectl -n ops-ai delete job migrate` and `kubectl apply -k <overlay>`, since a finished Job cannot change |

## How it behaves

- Every service checks the database's schema version at start and refuses one it does not match, naming the upgrade
  that is missing. Two releases cannot be mixed by mistake.
- Each step of `upgrade.sql` checks the version it starts from and stops before any change when the database is
  somewhere else, so running it twice is refused.
- Some steps move rows that the running release still writes. Stop the services before the database step, and start
  only the new release after it. Agents 0120 (stored skill step tools) does not need the stop: it rewrites skill and
  agent versions one batch per transaction, each batch setting its table's policy aside and putting it back, so the
  services keep serving. A version the earlier release saves after its last pass is refused by the publish check and
  the attach until its builder marks the step's tool.

## Roll back

Migrations do not roll back on their own. Either restore the backup taken before the upgrade, or have your DBA run the
release's `downgrade.sql` where every step has one; then start the previous images. The script does this for you when
its check fails.

## Limits

- On a table over about a million rows, an index the upgrade adds holds writes while it builds. The upgrade names such
  indexes; build them first with `CREATE INDEX CONCURRENTLY` and the upgrade finds them.
- Upgrades from the dated releases before 1.0.0 run through the schema job only, not the DBA scripts.
