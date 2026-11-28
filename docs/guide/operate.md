# Run Ops AI day to day

Status: current.

Once Ops AI is installed, people depend on it. Someone on your team needs to know whether it is healthy, how to move it
to a new release without losing work, how to recover it after a mistake, and how to change a key without locking
everyone out. This page is the checklist for that person. Health checks, upgrades and backups each have their own page, with the
install script's commands first and the Compose and Kubernetes commands for installs made by hand after them.

<!-- guide: include from "## Check the install" until "## Limits" -->
Check health, read logs, know what to watch and how to scale: [Monitor](../deploy/monitoring.md).

<!-- guide: include from "## Upgrade with the script" until "## Limits" -->
Move to a new release and roll back: [Upgrade](../deploy/upgrade.md).

<!-- guide: include from "## Back up and restore with the script" until "## Limits" -->
Back up the database, the stored files and the keys, and restore them: [Back up and restore](../deploy/backup-and-restore.md).

## Rotate keys

Ops AI uses several keys, and each is changed in its own way. Two of them have consequences you should plan for before
you start: changing the sign-in token key signs people out, and changing the secrets key makes every stored credential
unreadable.

| Key | Steps |
|---|---|
| Approval key (`OPS_REVIEW_KEY`) | Set the new value for the agents and tools services and restart both. Approvals that are waiting must be given again |
| A service's signing key | Give the service a new key and key id. Add its public key to every other service's trusted list beside the old one, restart the other services, then restart the service itself. Finally remove the old key id and restart the others again |
| Sign-in token key (`OPS_PLATFORM_SIGNING_KEY`) | Set a new key and key id and restart every service. People may need to sign in again |
| Secrets key (`OPS_SECRETS_KEY`) | Avoid changing it for now. Changing it makes every stored credential unreadable, so each one must be entered again, and a rotation that re-encrypts them is planned |
| A provider's model key | A Security admin replaces it in the credential store. No restart is needed |
| Database passwords | Change each login's password, update that service's setting and restart the service |

## Remove an install

Take a backup first if you may want the data. `./install.sh uninstall` asks for confirmation and removes the containers. It then asks a second time before it deletes
the data, and it keeps `ops-ai.env` in either case. If you installed by hand, `docker compose ... down` keeps the
volumes and `down -v` deletes them. On Kubernetes, `kubectl delete -k <overlay>` removes the volume claims with it.

## Limits

- An upgrade across two releases that change the schema has not run yet, because 1.0.0 is the first release.
- Metrics are planned. Health checks and logs are built.
- Ops AI schedules no backups. Run the backup from your scheduler, or use your database's own backups.
