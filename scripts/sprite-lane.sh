#!/usr/bin/env bash
# One sprite, one checkout. The laptop keeps its own checkout and its ports.
# This never runs `sprite use`, and exec never forwards a local port.
#
#   scripts/sprite-lane.sh add <name>
#   scripts/sprite-lane.sh exec <name> -- <command>
#
# A warm cloud box is the same sprite with the stack set up inside it (scripts/box-setup.sh). A name that starts with
# ops-ai- is used as given (ops-ai-box-1); any other name becomes ops-ai-lane-<name>.
#   scripts/sprite-lane.sh up <name> [branch]   create or wake the box and set the stack up in it
#   scripts/sprite-lane.sh url <name>           print the one-time link that opens the box in a browser
#   scripts/sprite-lane.sh check <name>         headless through the public address: gate, link, sign-in, chat, API
#   scripts/sprite-lane.sh status <name>        awake or asleep, the branch, the stack's health
#   scripts/sprite-lane.sh sleep <name>         close sessions, leave the stack running, wait for the box to go cold
#   scripts/sprite-lane.sh stop <name>          stop the stack and the side services too, then wait for cold
#   scripts/sprite-lane.sh reset <name> [branch]  fresh main (or the branch) and the seeded database
set -euo pipefail

org=${SPRITE_ORG:-chanl}
die() { echo "sprite-lane: $*" >&2; exit 1; }
sprite_bin() { printf '%s\n' "${SPRITE_BIN:-sprite}"; }

sprite_name() {
  if [[ "$1" =~ ^ops-ai-[a-z0-9-]{1,40}$ ]]; then printf '%s\n' "$1"; return; fi
  [[ "$1" =~ ^[a-z][a-z0-9-]{0,30}$ ]] || die "name is a lowercase letter, then lowercase letters, digits or hyphens"
  printf 'ops-ai-lane-%s\n' "$1"
}

exists() { "$(sprite_bin)" list -o "$org" --prefix "$1" 2>/dev/null | grep -q "^$1 *$"; }
box_json() { "$(sprite_bin)" api -o "$org" -s "$1" / -- -s 2>/dev/null | sed -n '/^{/p'; }
box_url() { box_json "$1" | python3 -c 'import json,sys; print(json.load(sys.stdin)["url"].rstrip("/"))'; }
# Read from the box over the CLI; only `url` and `check` use it, and `check` hands it to node through the environment.
box_key() { "$(sprite_bin)" exec -o "$org" -s "$1" --no-port-forward -- bash -c 'cat "$HOME/box/key"' 2>/dev/null | tr -d '\r\n'; }
box_state() { box_json "$1" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])'; }

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
  up | reset)
    verb=$1
    name=${2:?usage: sprite-lane.sh $verb <name>${verb/reset/}}
    sprite=$(sprite_name "$name")
    branch=${3:-main}
    exists "$sprite" || "$(sprite_bin)" create --skip-console -o "$org" "$sprite"
    origin=$(box_url "$sprite")
    # The address is public; the box's own gate (scripts/box-setup.sh) admits only browsers that opened the link from
    # `make box-url`. Fly's org-only setting would strip the app's Authorization header on every call.
    "$(sprite_bin)" config update -o "$org" -s "$sprite" --url-auth public >/dev/null
    reset_flag=; [ "$verb" = reset ] && reset_flag=1
    "$(sprite_bin)" exec -o "$org" -s "$sprite" --no-port-forward -- \
      env "BRANCH=$branch" "OPS_PUBLIC_ORIGIN=$origin" "BOX_RESET=$reset_flag" bash -s <"$(dirname "$0")/box-setup.sh"
    ;;
  url)
    sprite=$(sprite_name "${2:?usage: sprite-lane.sh url <name>}")
    "$(sprite_bin)" config update -o "$org" -s "$sprite" --url-auth public >/dev/null
    key=$(box_key "$sprite")
    echo "$(box_url "$sprite")/__box?key=$key"
    ;;
  check)
    sprite=$(sprite_name "${2:?usage: sprite-lane.sh check <name>}")
    BOX_KEY=$(box_key "$sprite") node "$(dirname "$0")/box-check.mjs" "$(box_url "$sprite")"
    ;;
  status)
    sprite=$(sprite_name "${2:?usage: sprite-lane.sh status <name>}")
    exists "$sprite" || die "no box named $sprite"
    state=$(box_state "$sprite")
    echo "$sprite: $state"
    # A box that is asleep is not woken to be asked.
    if [ "$state" = running ] || [ "$state" = warm ]; then
      "$(sprite_bin)" exec -o "$org" -s "$sprite" --no-port-forward -- bash -c \
        'cd ~/ops-ai 2>/dev/null && echo "branch: $(git rev-parse --abbrev-ref HEAD)@$(git rev-parse --short HEAD)" && OPS_INFRA=external make -s health 2>&1 | tail -16'
    fi
    ;;
  sleep | stop)
    verb=$1
    sprite=$(sprite_name "${2:?usage: sprite-lane.sh $verb <name>}")
    exists "$sprite" || die "no box named $sprite"
    # stop also stops the app and the box's services. sleep leaves them running: a box with nothing connected is
    # suspended by Fly with its processes intact (same pids, connections still open), so the next wake is instant.
    if [ "$verb" = stop ]; then
      "$(sprite_bin)" exec -o "$org" -s "$sprite" --no-port-forward -- bash -c \
        'cd ~/ops-ai 2>/dev/null && OPS_INFRA=external make -s down KEEP_DB=1 >/dev/null 2>&1; for s in $(sprite-env services list 2>/dev/null | grep -o "\"name\": *\"[^\"]*\"" | cut -d\" -f4); do sprite-env services stop "$s" >/dev/null 2>&1; done; true'
    fi
    # The exec above has ended, so no session is open. Fly suspends the box a few minutes later.
    start=$SECONDS
    while [ $((SECONDS - start)) -lt "${BOX_SLEEP_WAIT:-420}" ]; do
      state=$(box_state "$sprite")
      if [ "$state" = cold ]; then
        echo "$sprite: $state after $((SECONDS - start))s"
        exit 0
      fi
      sleep "${BOX_SLEEP_POLL:-5}"
    done
    die "$sprite is still $state after ${BOX_SLEEP_WAIT:-420}s"
    ;;
  *)
    sed -n '2,24p' "$0" >&2
    exit 2
    ;;
esac
