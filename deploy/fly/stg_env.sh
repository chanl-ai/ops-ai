# Sourced by deploy/fly/stg_deploy.sh and make/staging.mk: loads the Fly app names for staging from
# $OPS_STAGING_CONFIG/staging.env (default ~/.config/ops-ai/staging.env), so the repo carries none of them.
# Format: KEY=value lines, no quoting; a value already in the environment wins. Template: deploy/fly/staging.env.example.
stg_conf=${OPS_STAGING_CONFIG:-$HOME/.config/ops-ai}
stg_file=$stg_conf/staging.env
if [ ! -f "$stg_file" ]; then
  echo "staging: $stg_file not found. Copy deploy/fly/staging.env.example there and fill in your Fly app names." >&2
  exit 2
fi
while IFS='=' read -r k v; do
  case "$k" in
    STG_*) [ -n "$(printenv "$k")" ] || export "$k=$v" ;;
  esac
done < "$stg_file"
: "${STG_APP_PREFIX:=<your-app>}"
export STG_APP_PREFIX
for k in STG_APP STG_DB_APP; do
  if [ -z "$(printenv "$k")" ]; then
    echo "staging: $k is not set in $stg_file (see deploy/fly/staging.env.example)." >&2
    exit 2
  fi
done
# Staging tooling only ever touches apps with the configured prefix.
case "$STG_APP" in "$STG_APP_PREFIX"*) ;; *) echo "staging: STG_APP must start with $STG_APP_PREFIX" >&2; exit 2 ;; esac
case "$STG_DB_APP" in "$STG_APP_PREFIX"*) ;; *) echo "staging: STG_DB_APP must start with $STG_APP_PREFIX" >&2; exit 2 ;; esac
