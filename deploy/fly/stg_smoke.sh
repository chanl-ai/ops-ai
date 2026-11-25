#!/bin/sh
# make stg-smoke: the smoke check of a staging deploy (deploy/fly/smoke.mjs), run alone against the live staging app,
# with no build, deploy or rollback. It signs in as the roles team's admin (STG_ROLE_ADMIN in staging-roles.env) and makes,
# publishes and removes records in STG_ROLES_TEAM (OPS_SMOKE_TEAM overrides), so it writes to staging: the owner runs it.
# Ends on one `smoke:` line and exits non-zero when any check failed. Runbook: docs/deploy/fly-staging.md.
set -eu
root=$(cd "$(dirname "$0")/../.." && pwd)
. "$root/deploy/fly/stg_env.sh"
origin="https://$STG_APP.fly.dev"
roles="$stg_conf/staging-roles.env"
[ -r "$roles" ] || { echo "stg-smoke: no roles file at $roles (deploy/fly/staging-roles.env.example)" >&2; exit 2; }
pair() { grep "^$1=" "$roles" | cut -d= -f2-; }
team=${OPS_SMOKE_TEAM:-$(pair STG_ROLES_TEAM)}
[ -n "$team" ] || { echo "stg-smoke: STG_ROLES_TEAM is not set in $roles" >&2; exit 2; }
# The smoke check renews its session through the SDK transport, which runs from its build.
log=$(mktemp)
pnpm -C "$root/sdk/typescript" build >"$log" 2>&1 || { tail -20 "$log"; rm -f "$log"; exit 1; }
rm -f "$log"
echo "stg-smoke: $origin, team $team"
OPS_SMOKE_EMAIL=$(pair STG_ROLE_ADMIN_EMAIL) OPS_SMOKE_PASSWORD=$(pair STG_ROLE_ADMIN_PASSWORD) \
  OPS_SMOKE_TEAM="$team" exec node "$root/deploy/fly/smoke.mjs" "$origin"
