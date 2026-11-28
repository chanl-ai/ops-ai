# Upgrade to a new release

Status: current.

A new release arrives, and you need to move your install to it without losing the work that is in flight. The database
changes first and the services follow, and a run that is waiting for a person resumes on the new release with the
workflow or agent version it started on. The script takes a backup first and rolls back by itself if its check fails. Its upgrade, rollback and same-version
rerun have been run end to end on one machine. An upgrade across two releases that change the schema has not run yet,
because 1.0.0 is the first release.

## Upgrade with the script

Fetch the release and run the upgrade from the checkout:

```bash
git fetch --tags && git checkout v<new version>
./install.sh upgrade
```

The script works in this order.

<!-- site: sequence caption="What ./install.sh upgrade does, and what it does when its check fails" -->
1. **Install script → PostgreSQL**: Takes a backup
2. **Install script → Services**: Pulls the new images
3. **Install script → PostgreSQL**: Applies the schema
4. **Install script → Services**: Restarts them on the new version
5. **Install script → Services**: Checks the result
   - If the check fails, the script restores the backup on the old version and exits with an error.

If the install is already on that version, it checks and changes nothing. `--version V` upgrades to a version other than the checkout's. Afterwards, run `./install.sh status` and confirm that it
shows the new version.

In `dba` mode the script writes the upgrade scripts to `./dba/upgrade-<from>-to-<to>/` and waits for your DBA to apply
them. It also needs `--admin-url-file <file>` to take the backup.

## Upgrade by hand

<!-- site: steps -->
1. **Back up** the database and the stored files ([Back up and restore](backup-and-restore.md)).
2. **Upgrade the database.** Apply, as your DBA, the new release's `upgrade-roles.sql`, then `upgrade.sql` as the schema
   owner, then the new release's `grants.sql` ([Database](database.md#upgrade)).
3. **Start the new images.**

| Install | Command |
|---|---|
| Compose | Set `OPS_IMAGE_TAG` to the new version, then run `docker compose -p ops-ai -f deploy/compose/app.yaml --env-file ops-ai.env up -d`. In DBA mode, add `-f deploy/compose/dba.yaml`. Without a DBA, the schema job applies the upgrade before the services start |
| Kubernetes | Set the new tag in the overlay, then run `kubectl -n ops-ai delete job migrate` and `kubectl apply -k <overlay>`, because a finished Job cannot be changed |

## What to expect during an upgrade

- Every service checks the database's schema version when it starts and refuses a version it does not match, naming the
  upgrade that is missing. This keeps you from running two releases side by side by mistake.
- Each step of `upgrade.sql` checks the version it starts from. If the database is somewhere else, it stops before it
  changes anything, so running the same SQL script twice is refused.
- Some steps move rows that the running release still writes, so stop the services before the database step and start
  only the new release after it. The step that rewrites stored skill step tools is the exception. It works through skill
  and agent versions one batch at a time, so you can leave the services running while it runs. If the earlier release
  saves a version after that step's last pass, the version is refused when someone publishes or attaches it, until its
  builder marks the step's tool.

## Roll back

Migrations do not roll back on their own. You can restore the backup taken before the upgrade, or your DBA can run the
release's `downgrade.sql` where every step has one. Then start the previous images. The script does this for you when
its check fails. Restoring the backup drops anything people did after the upgrade began.

## Limits

- On a table with more than about a million rows, an index that the upgrade adds holds writes while it builds. The
  upgrade names such indexes, so you can build them first with `CREATE INDEX CONCURRENTLY` and the upgrade then uses them.
- Upgrades from the dated releases before 1.0.0 run through the schema job only, not through the DBA scripts.
