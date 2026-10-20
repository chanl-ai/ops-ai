#!/bin/sh
# The first tenant, Security team and admin (python -m ops_platform.bootstrap), when a first-admin password is set in
# the env or as a secret file; it changes nothing once the admin has a password, so it runs on every start. Called by
# migrate.sh after platform's chain, and alone by compose's migrate job on a schema the DBA applied (dba.yaml).
set -eu
here=$(cd "$(dirname "$0")" && pwd)
root=${OPS_ROOT:-$(cd "$here/../.." && pwd)}
python=${PYTHON:-$root/.venv/bin/python}
if [ -n "${OPS_BOOTSTRAP_ADMIN_PASSWORD:-}" ] || [ -s "${OPS_SECRETS_DIR:-/run/secrets}/ops_bootstrap_admin_password" ]; then
  exec "$python" -m ops_platform.bootstrap
fi
echo "first admin: OPS_BOOTSTRAP_ADMIN_PASSWORD unset; step skipped"
