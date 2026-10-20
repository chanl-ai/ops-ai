#!/bin/sh
# Applies migration chains in the order deploy/images/chains lists them, each to head or to `<chain>=<revision>`; with
# no arguments, every chain to head. When platform's chain is among them and a first-admin password is set (env or
# secret file), it then makes the first tenant, Security team and admin; that step changes nothing once the admin has a
# password. Called by compose's migrate job (deploy/compose/app.yaml), Fly's release command (deploy/fly/release.sh)
# and the schema tool (deploy/database/schema.py), in an image or a checkout.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
# OPS_ROOT runs another checkout's chains (the schema tool exports a git ref and migrates it with this script).
root=${OPS_ROOT:-$(cd "$here/../.." && pwd)}
alembic=${ALEMBIC:-$root/.venv/bin/alembic}
targets=${*:-$(grep -v '^#' "$here/chains")}
ran=""
for target in $targets; do
  svc=${target%%=*}
  rev=head
  [ "$svc" = "$target" ] || rev=${target#*=}
  echo "migrate: $svc-service to $rev"
  (cd "$root/services/$svc-service" && "$alembic" upgrade "$rev")
  ran="$ran $svc"
done
case "$ran " in
  *" platform "*)
    [ "${OPS_MIGRATE_SKIP_BOOTSTRAP:-0}" = 1 ] || "$here/first_admin.sh"
    ;;
esac
