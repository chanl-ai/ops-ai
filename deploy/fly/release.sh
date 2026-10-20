#!/bin/sh
# Fly's release_command: every service's migration chain, then the first admin (deploy/images/migrate.sh, which
# compose's migrate jobs run too). Runs on a temporary machine with the app's secrets before the new image starts; a
# failure stops the deploy.
set -eu
. /app/deploy/fly/env.sh
: "${OPS_DATABASE_URL:?set OPS_DATABASE_URL, or attach Postgres so DATABASE_URL is set}"
exec /app/deploy/images/migrate.sh
