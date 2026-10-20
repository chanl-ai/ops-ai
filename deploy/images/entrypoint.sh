#!/bin/sh
# Every Ops AI service image's entrypoint. Settings come from OPS_* env values, or from files under /run/secrets named
# after the setting (ops_review_key for OPS_REVIEW_KEY), which Settings reads itself (OPS_SECRETS_DIR moves the folder).
# `migrate [chain...]` applies migration chains (migrate.sh); anything else runs as given.
set -eu
if [ "${1:-}" = migrate ]; then
  shift
  exec /app/deploy/images/migrate.sh "$@"
fi
exec "$@"
