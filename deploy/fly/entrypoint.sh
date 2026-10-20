#!/bin/sh
# The container's main process: the process host, in the foreground, with the services OPS_ENABLED_SERVICES names.
# Given a command (Fly's release_command, `fly machine run ... <command>`), it runs that instead: Fly passes the release
# command to the image's entrypoint as arguments.
set -eu
. /app/deploy/fly/env.sh
[ "$#" = 0 ] || exec "$@"
: "${OPS_DATABASE_URL:?set OPS_DATABASE_URL, or attach Postgres so DATABASE_URL is set}"
mkdir -p "${OPS_FILES_DIR:-/data/files}" "${OPS_KB_FILES_DIR:-/data/kb-files}"
exec python3 /app/deploy/host/ops_host.py "${OPS_HOST_CONFIG:-/app/deploy/fly/processes.toml}"
