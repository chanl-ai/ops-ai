# Operate

Status: current.

Keep an install healthy once it runs: check it and read its logs, move it to a new release, back it up, and rotate its
keys. The install script's commands come first on each page; the Compose and Kubernetes commands follow for installs
made by hand.

<!-- guide: include from "## Check the install" until "## Limits" -->
Check health, read logs, know what to watch and how to scale: [Monitor](../deploy/monitoring.md).

<!-- guide: include from "## Upgrade with the script" until "## Limits" -->
Move to a new release and roll back: [Upgrade](../deploy/upgrade.md).

<!-- guide: include from "## Back up and restore with the script" until "## Limits" -->
Back up the database, the stored files and the keys, and restore them: [Back up and restore](../deploy/backup-and-restore.md).

## Rotate keys

| Key | Steps |
|---|---|
| Approval key (`OPS_REVIEW_KEY`) | Set the new value for agents and tools and restart both. Approvals in flight must be given again |
| A service's signing key | Give the service a new key and key id, add its public key to every other service's trusted list beside the old one, restart the others, then the service; then remove the old key id and restart the others again |
| Sign-in token key (`OPS_PLATFORM_SIGNING_KEY`) | Set a new key and key id and restart every service; people may need to sign in again |
| Secrets key (`OPS_SECRETS_KEY`) | Changing it makes every stored credential unreadable, so each must be entered again. A rotation that re-encrypts them is planned |
| A provider's model key | A Security admin replaces it in the credential store; no restart |
| Database passwords | Change each login's password, update its setting, restart that service |

## Remove

`./install.sh uninstall` asks, then removes the containers, and asks again before deleting the data. It keeps
`ops-ai.env`. By hand: `docker compose ... down` keeps the volumes and `down -v` deletes them; on Kubernetes,
`kubectl delete -k <overlay>` removes the volume claims with it.

## Limits

- An upgrade across two releases that change the schema has not run yet: 1.0.0 is the first release.
- Metrics are planned; health checks and logs are built.
- Ops AI schedules no backups; run the backup from your scheduler or use your database's own.
