#!/bin/sh
# Builds the TypeScript SDK package (@chanl-ai/ops-ai) when its sources are newer than its dist, so a console typecheck
# never judges against declarations from before the last SDK regeneration (51 console type errors once passed the
# commit hook that way). The console imports the package through its dist (sdk/typescript/package.json "types").
#   ensure-sdk-ts-built.sh [sdk-dir]    default: sdk/typescript of this checkout
#   ensure-sdk-ts-built.sh --self-test  plants a newer source file and sees the build triggered
set -eu
here=$(cd "$(dirname "$0")/.." && pwd)

stale() { # $1 = sdk dir; true when dist is missing or any source or config file is newer than dist/index.d.ts
  [ -f "$1/dist/index.d.ts" ] || return 0
  [ -n "$(find "$1/src" "$1/package.json" "$1/tsconfig.json" -newer "$1/dist/index.d.ts" -type f 2>/dev/null | head -1)" ]
}

if [ "${1:-}" = "--self-test" ]; then
  t=$(mktemp -d "${TMPDIR:-/tmp}/sdk-built.XXXXXX")
  trap 'rm -rf "$t"' EXIT
  mkdir -p "$t/src" "$t/dist"
  : >"$t/package.json"; : >"$t/tsconfig.json"; : >"$t/dist/index.d.ts"
  sleep 1; : >"$t/dist/index.d.ts"
  if stale "$t"; then echo "self-test: FAILED, a fresh dist was called stale"; exit 1; fi
  sleep 1; echo "export {}" >"$t/src/index.ts"
  if ! stale "$t"; then echo "self-test: FAILED, a source newer than dist was not noticed"; exit 1; fi
  rm "$t/dist/index.d.ts"
  if ! stale "$t"; then echo "self-test: FAILED, a missing dist was not noticed"; exit 1; fi
  echo "self-test: a stale or missing sdk dist is rebuilt, a fresh one is left"
  exit 0
fi

dir=${1:-$here/sdk/typescript}
if stale "$dir"; then
  echo "sdk/typescript dist is older than its sources: building it before the console typecheck" >&2
  (cd "$dir" && ./node_modules/.bin/tsc -p tsconfig.json)
fi
