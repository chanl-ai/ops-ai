#!/usr/bin/env bash
# One sprite, one checkout. The laptop keeps its own checkout and its ports.
# This never runs `sprite use`, and exec never forwards a local port.
#
#   scripts/sprite-lane.sh add <name>
#   scripts/sprite-lane.sh exec <name> -- <command>
set -euo pipefail

org=${SPRITE_ORG:-chanl}
die() { echo "sprite-lane: $*" >&2; exit 1; }
sprite_bin() { printf '%s\n' "${SPRITE_BIN:-sprite}"; }

sprite_name() {
  [[ "$1" =~ ^[a-z][a-z0-9-]{0,30}$ ]] || die "name is a lowercase letter, then lowercase letters, digits or hyphens"
  printf 'ops-ai-lane-%s\n' "$1"
}

case "${1:-}" in
  add)
    name=${2:?usage: sprite-lane.sh add <name>}
    sprite=$(sprite_name "$name")
    "$(sprite_bin)" create --skip-console -o "$org" "$sprite"
    ;;
  exec)
    name=${2:?usage: sprite-lane.sh exec <name> -- <command>}
    shift 2
    [ "${1:-}" = "--" ] || die "usage: sprite-lane.sh exec <name> -- <command>"
    shift
    [ "$#" -gt 0 ] || die "usage: sprite-lane.sh exec <name> -- <command>"
    sprite=$(sprite_name "$name")
    "$(sprite_bin)" exec -o "$org" -s "$sprite" --no-port-forward -- "$@"
    ;;
  *)
    sed -n '2,6p' "$0" >&2
    exit 2
    ;;
esac
