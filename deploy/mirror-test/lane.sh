#!/usr/bin/env bash
# make qa-mirror: the behind-a-mirror lane. A clean install of both lockfiles through our own Nexus on a network with no
# other way out, a fast test subset, then the age, vulnerability and licence checks. Exits 0 only when every step passed.
#
#   deploy/mirror-test/lane.sh           run the lane; stops Nexus afterwards (its cache volume stays for the next run)
#   MIRROR_KEEP_UP=1 ...                 leave Nexus running
#   deploy/mirror-test/lane.sh down      stop Nexus and delete its cache volume
#
# Its own compose project (ops-mirror-test) and networks; nothing of the shared dev stack is touched.
set -uo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
PORT=${OPS_MIRROR_PORT:-18081}
cd "$HERE"
compose() { docker compose -f "$HERE/compose.yaml" "$@"; }
say() { printf '%s\n' "$*"; }
failed=""
fail() { say "FAIL: $*"; failed="${failed:+$failed; }$*"; }

if [ "${1:-}" = down ]; then compose down -v; exit 0; fi

# The files an install reads: tracked and new files under the code folders and the root manifests, no docs or evidence. From a checkout git lists them;
# from a plain export (the QA runner tests one) a find does.
filelist=$(mktemp)
trap 'rm -f "$filelist"' EXIT
(cd "$ROOT" && if git rev-parse --git-dir >/dev/null 2>&1; then git ls-files -z --cached --others --exclude-standard
  else find . -type f -not -path './node_modules/*' -not -path '*/node_modules/*' -not -path './.venv/*' -not -path '*/.next/*' -print0; fi) |
  python3 -c '
import os, sys
keep = ("packages/", "services/", "apps/", "sdk/", "scripts/", "deploy/", "changelog/")
for f in sys.stdin.buffer.read().split(b"\0"):
    s = f.decode().removeprefix("./")
    top_level = s and "/" not in s
    if (top_level or s.startswith(keep)) and "/node_modules/" not in s and os.path.isfile(os.path.join(sys.argv[1], s)):
        sys.stdout.buffer.write(s.encode() + b"\0")' "$ROOT" >"$filelist"

say "== Nexus up, repositories made"
compose up -d nexus >/dev/null || { fail "Nexus did not start"; exit 1; }
"$HERE/nexus.sh" setup || { fail "Nexus setup"; exit 1; }
compose --profile installer build installer >/dev/null || { fail "installer image build"; exit 1; }

say "== install both lockfiles through Nexus, in a container whose only network is Nexus's"
log=$(mktemp)
COPYFILE_DISABLE=1 tar -C "$ROOT" --null -T "$filelist" -cf - 2>/dev/null |
  compose run --rm -T installer sh -c 'tar -xf - -C /work 2>/dev/null; sh deploy/mirror-test/inside.sh' 2>&1 | tee "$log" |
  grep -E '^(==|FAIL|PASS  |no route|licences:|age:|INSTALL-THROUGH|[0-9]+ passed|# (tests|pass|fail) )|installed [0-9]+ packages|Done in'
grep -q '^INSTALL-THROUGH-MIRROR: PASS' "$log" || fail "the install through Nexus (full output: $log)"

say "== Nexus served the install"
count() { python3 - "http://127.0.0.1:$PORT/service/rest/v1/components?repository=$1" <<'PY'
import json, sys, urllib.request

url, token, total = sys.argv[1], None, 0
while True:
    with urllib.request.urlopen(url + (f"&continuationToken={token}" if token else "")) as r:
        doc = json.load(r)
    total += len(doc["items"])
    token = doc.get("continuationToken")
    if not token:
        break
print(total)
PY
}
py=$(count pypi-proxy); npm=$(count npm-proxy)
say "Nexus cached $py Python and $npm npm components"
[ "${py:-0}" -ge 150 ] && [ "${npm:-0}" -ge 400 ] || fail "Nexus cached too few components ($py Python, $npm npm): the install did not go through it"

say "== no locked version is younger than 30 days (Nexus has no age rule, so the lane enforces it)"
NPM_CONFIG_REGISTRY="http://127.0.0.1:$PORT/repository/npm-proxy/" python3 "$ROOT/scripts/deps_audit.py" age || fail "age"

say "== known vulnerabilities in both lockfiles"
python3 "$ROOT/scripts/deps_audit.py" vulns || fail "vulnerabilities"

[ "${MIRROR_KEEP_UP:-0}" = 1 ] || compose stop nexus >/dev/null
if [ -n "$failed" ]; then say "qa-mirror: FAIL ($failed)"; exit 1; fi
say "qa-mirror: PASS"
