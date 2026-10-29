#!/bin/sh
# Runs inside the install container (compose.yaml, service installer), in /work, which holds a copy of the checkout.
# The container's only network is the one Nexus is on, so a download that skips the mirror fails by itself; the first
# step proves that, and every later step installs from the mirror or fails.
set -eu
cd /work

step() { printf '\n== %s\n' "$*"; }

# Docker's embedded resolver drops queries when pnpm opens dozens of connections at once (EAI_AGAIN); one lookup, kept
# in /etc/hosts, avoids the resolver for the rest of the run.
getent ahostsv4 nexus | awk 'NR == 1 { print $1, "nexus" }' >>/etc/hosts

step "the container reaches Nexus and nothing else"
ok=0
for _ in 1 2 3 4 5 6; do
  if curl -sf -m 30 -o /dev/null "$UV_DEFAULT_INDEX/idna/"; then ok=1; break; fi
  sleep 5
done
[ "$ok" = 1 ] || { echo "FAIL: Nexus does not answer at $UV_DEFAULT_INDEX"; exit 1; }
for url in https://pypi.org/simple/ https://files.pythonhosted.org/ https://registry.npmjs.org/ https://github.com/ https://ghcr.io/; do
  if curl -s -m 5 -o /dev/null "$url"; then echo "FAIL: reached $url without going through the mirror"; exit 1; fi
  echo "no route to $url"
done

step "make setup's mirror answers, tested through Nexus before anything is installed"
# Setup is the standard library apart from the database driver, so it runs here first; with nothing installed yet its
# database line says to run make install, and its two mirror lines must pass through Nexus.
printf 'RUNS_ON=docker\nDOCKER=no\nDATABASE=postgresql://ops:ops@nexus:5432/ops\nPYPI_MIRROR=%s\nNPM_MIRROR=%s\nIMAGE_REGISTRY=none\nMODEL_PROVIDER=fake\n' \
  "$UV_DEFAULT_INDEX" "$NPM_CONFIG_REGISTRY" >/tmp/setup-answers.env
SETUP_FILE=/tmp/setup.env PYTHONPATH=scripts:deploy/database python3 -m setup --answers /tmp/setup-answers.env >/tmp/setup.out || true
cat /tmp/setup.out
grep -q '^PASS  pypi mirror' /tmp/setup.out && grep -q '^PASS  npm mirror' /tmp/setup.out ||
  { echo "FAIL: make setup did not pass the mirrors"; exit 1; }

step "Python: the locked versions, installed from the mirror"
bash scripts/install_via_mirror.sh

step "npm: pnpm install --frozen-lockfile from the mirror (pnpm itself through corepack)"
corepack enable pnpm
COREPACK_NPM_REGISTRY=$COREPACK_NPM_REGISTRY corepack prepare --activate
pnpm --version
pnpm install --frozen-lockfile

step "fast tests"
bash scripts/deps_smoke.sh

step "licences of what was installed"
/work/.venv/bin/python scripts/deps_audit.py licenses

printf '\nINSTALL-THROUGH-MIRROR: PASS\n'
