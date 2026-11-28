#!/usr/bin/env bash
# The pre-commit gate (`pnpm verify`) on what is being committed, not on the working tree. Builders share one tree, so a
# half-written file of someone else's would otherwise fail every commit. The commit's index (GIT_INDEX_FILE, which a
# pathspec commit points at its own temporary index) is exported to a temporary directory; dependencies are linked from
# the tree; the gates run there with git reading that same index, so check-docs lists the committed files only.
set -euo pipefail
# /usr/local/bin/git on this Mac is an Intel build, so a hook it starts runs under Rosetta and the universal Python
# picks its Intel half, which cannot load the arm64 extensions in .venv. Re-run the gate natively on Apple silicon.
if [ "$(uname -s)" = Darwin ] && [ "$(uname -m)" = x86_64 ] && [ "$(sysctl -n sysctl.proc_translated 2>/dev/null)" = 1 ] && [ -z "${OPS_GATE_NATIVE:-}" ]; then
  nb=/opt/homebrew/bin/bash; [ -x "$nb" ] || nb=$(command -v bash)
  OPS_GATE_NATIVE=1 exec arch -arm64 "$nb" "$0" "$@"
fi
root="$(git rev-parse --show-toplevel)"
git_dir="$(git -C "$root" rev-parse --absolute-git-dir)"
# A fresh worktree has no .venv; every Python check below would then fail with a missing-interpreter error that the
# scrub check's own message would hide. The main checkout's environments are linked in (scripts/lane.sh, as `make lane`
# does); only a main checkout that has none itself is refused.
if [ ! -x "$root/.venv/bin/python" ]; then
  bash "$root/scripts/lane.sh" --link "$root" || true
fi
if [ ! -x "$root/.venv/bin/python" ]; then
  echo "verify-staged: no .venv here or in the main checkout; run pnpm install (and uv sync) in $root, then commit again"
  exit 1
fi
index="${GIT_INDEX_FILE:-$git_dir/index}"
case "$index" in /*) ;; *) index="$PWD/$index" ;; esac
# The export of the index lives in the worktree's git folder and is brought up to date by changed paths only
# (scripts/sync-staged-tree.sh); a fresh export of every tracked file took seconds on each commit. `tmp` keeps the name of
# the folder the checks run in. Scratch files of this run go in a per-run folder, so the shared tree holds the index's
# content and nothing else.
run="$(mktemp -d "${TMPDIR:-/tmp}/ops-ai-staged.XXXXXX")"
trap 'rm -rf "$run"' EXIT
# The shared export is used only when this run is inside a commit that holds the commit lock (scripts/commit-lock.sh), so
# two runs never rewrite it at once. A plain `git commit` that skipped the lock gets a private export, as before.
common="$(cd "$(git -C "$root" rev-parse --git-common-dir)" && pwd)"
lock_pid="$(cat "$common/commit.lock/pid" 2>/dev/null || true)"
shared=0
if [ -n "$lock_pid" ]; then
  p=$$
  while [ -n "$p" ] && [ "$p" -gt 1 ]; do
    if [ "$p" = "$lock_pid" ]; then shared=1; break; fi
    p="$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ')"
  done
fi
if [ "$shared" = 1 ]; then tmp="$git_dir/staged-tree"; list="$git_dir/staged-tree.list"; tsc_state="$git_dir/staged-tsc"
else tmp="$run/tree"; list="$run/tree.list"; tsc_state="$run/tsc"; fi
# Mechanical fixes first, so the checks below see the fixed content: ruff's safe fixes and the formatter on the staged
# Python files. Only a file whose working copy equals its staged copy is touched (no partial staging, no unstaged edits
# of another builder); the fixed file is staged again by its own path. The console has no formatter or fixing linter
# configured, so nothing runs there.
mapfile -t fixable < <(GIT_INDEX_FILE="$index" git -C "$root" diff --cached --name-only --diff-filter=ACMR -- '*.py' || true)
fix_skipped=()
if [ "${#fixable[@]}" -gt 0 ] && [ -x "$root/.venv/bin/ruff" ]; then
  for f in "${fixable[@]}"; do
    if ! GIT_INDEX_FILE="$index" git -C "$root" diff --quiet -- "$f"; then fix_skipped+=("$f"); continue; fi
    before="$(git -C "$root" hash-object -- "$f")"
    (cd "$root" && "$root/.venv/bin/ruff" check --fix --quiet -- "$f" >/dev/null 2>&1 || true; "$root/.venv/bin/ruff" format --quiet -- "$f" >/dev/null 2>&1 || true)
    if [ "$(git -C "$root" hash-object -- "$f")" != "$before" ]; then
      GIT_INDEX_FILE="$index" git -C "$root" add -- "$f"
      echo "verify-staged: fixed $f (ruff safe fixes and format), staged again"
    fi
  done
fi
if [ -x "$root/scripts/sync-staged-tree.sh" ]; then
  "$root/scripts/sync-staged-tree.sh" "$index" "$tmp" "$list"
else
  rm -rf "$tmp" "$list"; mkdir -p "$tmp"; GIT_INDEX_FILE="$index" git -C "$root" checkout-index -a --prefix="$tmp/"
fi
# apps/embed/node_modules: console verify type-checks the embed app too, which draws the console's chat components.
# sdk/typescript/node_modules: the sdk gate runs openapi-typescript from there.
for dep in node_modules apps/console/node_modules apps/embed/node_modules packages/usecase-runner/node_modules sdk/typescript/node_modules; do
  if [ -e "$root/$dep" ] && [ -d "$(dirname "$tmp/$dep")" ]; then ln -sfn "$root/$dep" "$tmp/$dep"; fi
done
# The Python checks run on the checkout's own environment ($root/.venv/bin/...), which is never linked into the export:
# the export is a whole uv workspace, so a `uv run` inside it would reinstall every member into a linked .venv pointing
# at this temporary folder, and the checkout's imports would break once the folder is deleted. UV_NO_SYNC stops any uv
# call made from here from installing anything at all.
export UV_NO_SYNC=1
cd "$tmp"
# Each check below runs only when a staged path can change its result: a docs-only commit ran all the console's
# tests and read every tracked file. The thorough per-service tests run before a push (.githooks/pre-push), and the
# full suite on each new HEAD (the QA runner) and before a snapshot leaves (repo.sh).
mapfile -t staged < <(GIT_INDEX_FILE="$index" git -C "$root" diff --cached --name-only --diff-filter=ACMRD || true)
mapfile -t present < <(GIT_INDEX_FILE="$index" git -C "$root" diff --cached --name-only --diff-filter=ACMR || true)
# A here-string, not a pipe: under pipefail, grep -q leaving early can fail a long printf with SIGPIPE.
touches() { [ "${#staged[@]}" -gt 0 ] && grep -qE "$1" <<<"$(printf '%s\n' "${staged[@]}")"; }
# The console's typecheck, standards and tests (apps/console/CLAUDE.md), and the embed app's typecheck, which draws the
# console's chat components.
# Static checks run on every commit (ruff, pyright on the staged Python, incremental console typecheck, the console
# standards); the slow ones (console unit tests, the standards self-test, make checks) run only with OPS_FULL_HOOK=1,
# because CI's merge queue runs them once per group of pull requests.
if touches '^apps/(console|embed)/|^package\.json$|^pnpm-lock\.yaml$'; then
  # The same steps as `pnpm --filter @ops-ai/console verify` (apps/console/package.json), with two differences that do not
  # change what is judged. The type checks are incremental: their state lives next to the persistent export, so only the
  # files that changed since the last commit check, and their dependents, are checked again, with the same errors.
  # The unit tests are the ones next to the staged sources (the whole suite runs in .githooks/pre-push).
  if [ ! -d "$root/node_modules" ] || [ ! -d "$root/apps/console/node_modules" ]; then
    echo "verify-staged: this worktree has no node_modules; run pnpm install (and uv sync) in $root, then commit again"
    exit 1
  fi
  mkdir -p "$tsc_state"
  tsc="$tmp/apps/console/node_modules/.bin/tsc"
  (
    cd "$tmp/apps/console"
    "$tsc" --noEmit --incremental --tsBuildInfoFile "$tsc_state/console.tsbuildinfo"
    "$tsc" --noEmit -p ../embed --incremental --tsBuildInfoFile "$tsc_state/embed.tsbuildinfo"
    GIT_DIR="$git_dir" GIT_WORK_TREE="$tmp" GIT_INDEX_FILE="$index" node scripts/check-standards.mjs
    if [ -n "${OPS_FULL_HOOK:-}" ]; then GIT_DIR="$git_dir" GIT_WORK_TREE="$tmp" GIT_INDEX_FILE="$index" node scripts/check-standards.mjs --self-test; fi
  )
  [ -n "${OPS_FULL_HOOK:-}" ] || tests_skip=1
  tests=(); sources=0
  for f in "${staged[@]}"; do
    case "$f" in
      apps/console/*.md|apps/embed/*.md) ;;
      apps/console/*.test.ts|apps/embed/*.test.ts) if [ -f "$tmp/$f" ]; then tests+=("$tmp/$f"); fi ;;
      apps/console/*|apps/embed/*|package.json|pnpm-lock.yaml)
        sources=1
        case "$f" in *.ts|*.tsx) sib="${f%.*}.test.ts"; if [ -f "$tmp/$sib" ]; then tests+=("$tmp/$sib"); fi ;; esac ;;
    esac
  done
  if [ -n "${tests_skip:-}" ]; then :
  elif [ "${#tests[@]}" -gt 0 ]; then
    mapfile -t tests < <(printf '%s\n' "${tests[@]}" | sort -u)
    (cd "$tmp/apps/console" && node --test "${tests[@]}")
  elif [ "$sources" = 1 ]; then
    # Nothing next to the staged files: the whole suite, as before.
    (cd "$tmp/apps/console" && node --test 'src/**/*.test.ts')
  fi
fi
# Where docs live, on the staged files; docs/README.md is always named, so the index's entries are checked even when the
# commit only deletes. The private-path scan reads the staged files only.
GIT_DIR="$git_dir" GIT_WORK_TREE="$tmp" GIT_INDEX_FILE="$index" node scripts/check-docs.mjs docs/README.md "${present[@]}"
if touches '^scripts/check-public-paths\.mjs$'; then node scripts/check-public-paths.mjs --self-test; fi
if [ "${#present[@]}" -gt 0 ]; then node scripts/check-public-paths.mjs "${present[@]}"; fi
if [ "${#present[@]}" -gt 0 ]; then
  "$root/.venv/bin/python" "$root/scripts/scrub_board_paths.py" --root "$PWD" --check "${present[@]}" \
    || { echo "verify-staged: a staged file names a home path or the machine login; run uv run python scripts/scrub_board_paths.py --apply"; exit 1; }
fi
# Every check a commit can break is a name on the one list (make/checks.mk): the migration downgrades, test token
# lifetimes, imports between services and the code rules of every service among them. They run on this export with the
# export's own sources first (the shared venv's editable installs read the working tree, where other builders'
# uncommitted files would decide the result), so a commit that breaks one cannot turn HEAD red for every builder.
export_path="$(ls -d "$PWD"/packages/*/src "$PWD"/services/*/src 2>/dev/null | tr '\n' ':')$PWD/deploy/database:$PWD"
# The one list of checks (make/checks.mk), each run when a staged path can change its result: access decided outside
# can(), the standards ratchets and their history, the files written from code, import directions, the SDK drift check.
# CI's checks job and `make verify` run the same list. They run on this export with the checkout's own tools; GIT_DIR
# lets the history checks read the commits already made, which the export does not have.
printf '%s\n' "${staged[@]}" > "$run/.staged"
# A service's typecheck target runs `uv run pyright`, which would build an environment in the export; this `uv` runs the
# command from the checkout's own environment instead. Any other uv command (the SBOM check's `uv export --frozen` on a
# lock change) goes to the real uv, which reads the export's lock and writes nothing.
real_uv="$(command -v uv || echo uv)"
mkdir -p "$run/.bin"
printf '#!/bin/sh\nif [ "$1" = run ]; then shift; exec "$@"; fi\nexec "%s" "$@"\n' "$real_uv" > "$run/.bin/uv"
chmod +x "$run/.bin/uv"
if [ -n "${OPS_FULL_HOOK:-}" ] && ! PATH="$run/.bin:$root/.venv/bin:$PATH" GIT_DIR="$git_dir" PYTHONPATH="$export_path" make -s -C "$tmp" checks STAGED=1 STAGED_FILES="$run/.staged" \
  PY="$root/.venv/bin/python" PYRIGHT="$root/.venv/bin/pyright" LINT_IMPORTS="$root/.venv/bin/lint-imports --no-logo" >"$run/.checks.log" 2>&1; then
  tail -60 "$run/.checks.log"; echo "verify-staged: make checks failed (above); fix what it names"; exit 1
fi
# Python files in the commit are linted and format-checked; a second each.
mapfile -t py < <(GIT_INDEX_FILE="$index" git -C "$root" diff --cached --name-only --diff-filter=ACMR -- '*.py' || true)
# A merge commit is checked on what it resolves: a file staged exactly as the other side has it came in with that side,
# so only files that differ from both parents are linted and type-checked here.
if [ "${#py[@]}" -gt 0 ] && git -C "$root" rev-parse -q --verify MERGE_HEAD >/dev/null; then
  mapfile -t theirs < <(GIT_INDEX_FILE="$index" git -C "$root" diff --cached --name-only --diff-filter=ACMR MERGE_HEAD -- '*.py' || true)
  kept=()
  for f in "${py[@]}"; do [[ " ${theirs[*]} " == *" $f "* ]] && kept+=("$f"); done
  py=("${kept[@]}")
fi
if [ "${#py[@]}" -gt 0 ]; then
  fixhint="verify-staged: ruff refused the files above; run uv run ruff check --fix <file> and uv run ruff format <file>, stage the file, commit again"
  if [ "${#fix_skipped[@]}" -gt 0 ]; then fixhint="$fixhint (not fixed here because the working copy differs from the staged copy: ${fix_skipped[*]})"; fi
  "$root/.venv/bin/ruff" check "${py[@]}" || { echo "$fixhint"; exit 1; }
  "$root/.venv/bin/ruff" format --check "${py[@]}" || { echo "$fixhint"; exit 1; }
  # Types on the staged Python files only (the project config decides strictness), from the checkout's environment.
  # Only files under the root config's `include` or an execution environment's root: pyright given any other file
  # checks it with no project settings, so a staging script or the SDK (its own project) fails on rules not its own.
  mapfile -t typed < <(cd "$root" && "$root/.venv/bin/python" -c 'import sys, tomllib; c = tomllib.load(open("pyproject.toml", "rb"))["tool"]["pyright"]; inc = c["include"] + [e["root"] for e in c.get("executionEnvironments", [])]; [print(f) for f in sys.argv[1:] if any(f == i or f.startswith(i.rstrip("/") + "/") for i in inc)]' "${py[@]}")
  if [ "${#typed[@]}" -eq 0 ]; then :
  elif [ -x "$root/.venv/bin/pyright" ]; then
    # In the export, so the staged content is what is checked (a file staged in a private index is not in the checkout);
    # imports resolve through the checkout's interpreter.
    # The venv's editable installs name the checkout's sources, so an absolute `import ops_agents...` would read the
    # checkout while a relative import reads the export, and one class then reads as two types. A project file for this
    # run puts the export's own source folders first in every environment (extraPaths come before site-packages).
    "$root/.venv/bin/python" - "$tmp" "$root" "$run/pyrightconfig.json" <<'PY'
import json, sys, tomllib
from pathlib import Path

# Resolved: pyright reports real paths, and a root under a symlinked /var would not match them.
tmp, root, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2]), Path(sys.argv[3])
cfg = tomllib.loads((tmp / "pyproject.toml").read_text())["tool"]["pyright"]
src = [str(d) for pat in ("packages/*/src", "services/*/src") for d in sorted(tmp.glob(pat))]
src += [str(tmp / "deploy/database")]
absolute = lambda p: str(tmp / p)
cfg.pop("include", None)  # the files are named on the command line; an absolute include is ignored with a warning
cfg["exclude"] = [e if e.startswith("**") else absolute(e) for e in cfg.get("exclude", [])]
envs = []
for e in cfg.get("executionEnvironments", []):
    e = dict(e)
    e["root"] = absolute(e["root"])
    e["extraPaths"] = [absolute(x) for x in e.get("extraPaths", [])] + src
    envs.append(e)
cfg["executionEnvironments"] = envs
cfg["extraPaths"] = [absolute(x) for x in cfg.get("extraPaths", [])] + src
cfg["venvPath"] = str(root)
out.write_text(json.dumps(cfg))
PY
    (cd "$tmp" && "$root/.venv/bin/pyright" --project "$run/pyrightconfig.json" --venvpath "$root" "${typed[@]}") || { echo "verify-staged: pyright refused the staged files above"; exit 1; }
  else
    echo "verify-staged: WARNING pyright is not installed in $root/.venv, so the staged Python was not type-checked; run uv sync"
  fi
fi
# Slower checks that build each service (OpenAPI documents, the generated SDKs, import directions, strict types, the
# SQL Server DDL and store tests) run in CI (the SQL Server ones in the merge queue) and in `make verify`, not on each commit. After a route
# or DTO change, `make openapi` regenerates every service's document and the SDKs in one step.
