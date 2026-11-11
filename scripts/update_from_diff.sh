#!/bin/sh
# make version | update-url | update-download | update-from-diff: update an install from a GitHub compare diff, for a team
# that can download files but has no git access (docs/deploy/install-guide.md, "Update from a downloaded diff").
#
#   version [COMMIT]     print the installed version; record it in VERSION from git HEAD, or from COMMIT (SET=)
#   url [TO]             the compare page from the installed version to TO (a release tag or commit; default main)
#   download TO          fetch that .diff over HTTPS into .run/updates/ (curl reads HTTPS_PROXY) and check it
#   apply FILE TO        check FILE starts at the installed version, apply it, record TO in VERSION
#
#   OPS_ROOT=<dir>         the install to update (default: the folder above this script)
#   UPDATE_BASE_URL=<url>  where compare pages live (default https://github.com/chanl-ai/ops-ai; tests use file://)
#
# VERSION is the only file this writes outside the diff; it is git-ignored, so a diff never collides with it. The start
# check compares each changed file with the blob hash the diff expects (git hash-object, needs no repository), so local
# edits to a tracked file are refused too; without git on the machine the dry run of patch is the check. TO must name a
# release or a commit: a branch moves, and the next update would start from the wrong place.
# A text diff cannot carry a binary file. Those entries are cut out, listed with where to download them, and the rest
# is applied. .env and .data are never in a diff (git-ignored), so they stay as they are.
set -eu

ROOT=${OPS_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}
BASE=${UPDATE_BASE_URL:-https://github.com/chanl-ai/ops-ai}
cd "$ROOT"

die() { echo "update: $*" >&2; exit 1; }
has_git() { command -v git >/dev/null 2>&1; }
is_git_folder() { [ -e .git ] && has_git; }

installed() {
  [ -s VERSION ] || die "no VERSION here; record the installed version once: make version SET=<commit or release>"
  tr -d ' \r\n' <VERSION
}

need_target() {
  case "${1:-}" in
    "") die "TO is missing: name the release or commit you are updating to, e.g. TO=v2026-11-12.1" ;;
    *[!0-9a-f]* | ??????) ;;
  esac
  if printf '%s' "$1" | grep -Eq '^[0-9a-f]{7,40}$|^v[0-9]{4}-[0-9]{2}-[0-9]{2}\.[0-9]+$'; then return 0; fi
  die "TO '$1' is not a release (vYYYY-MM-DD.N) or a commit; a branch name moves"
}

# Splits the diff in $1 into $WORK/text.diff (what can be applied), $WORK/binary.txt (paths a text diff cannot carry) and
# $WORK/start.txt ("path blob" for each file that exists before the change).
split_diff() {
  awk -v text="$WORK/text.diff" -v binary="$WORK/binary.txt" -v start="$WORK/start.txt" -v deleted="$WORK/deleted.txt" '
    function flush() {
      if (n == 0) return
      if (isbin) print path > binary
      else for (i = 1; i <= n; i++) print buf[i] > text
      if (del && !isbin) print path > deleted
      if (old != "" && old !~ /^0+$/) print path, old > start
      n = 0; isbin = 0; del = 0; old = ""
    }
    /^diff --git / { flush(); path = substr($3, 3) }
    /^deleted file mode / { del = 1 }
    /^index / { split($2, h, "[.][.]"); old = h[1] }
    /^Binary files / || /^GIT binary patch/ { isbin = 1 }
    { buf[++n] = $0 }
    END { flush() }
  ' "$1"
  : >>"$WORK/text.diff"; : >>"$WORK/binary.txt"; : >>"$WORK/start.txt"; : >>"$WORK/deleted.txt"
}

check_start() {
  split_diff "$1"
  grep -q '^diff --git ' "$1" || die "$1 is not a git diff"
  if has_git; then
    bad=
    while read -r path blob; do
      cur=$(git hash-object -- "$path" 2>/dev/null || echo missing)
      case $cur in "$blob"*) ;; *) bad="$bad $path" ;; esac
    done <"$WORK/start.txt"
    if [ -n "$bad" ]; then
      echo "update: this diff does not start at the installed version $(installed). These files differ from it:" >&2
      for p in $bad; do echo "  $p" >&2; done
      exit 1
    fi
  fi
}

cmd=${1:-}
[ $# -gt 0 ] && shift
WORK=$(mktemp -d "${TMPDIR:-/tmp}/ops-update.XXXXXX")
trap 'rm -rf "$WORK"' EXIT

case $cmd in
  version)
    if [ -n "${1:-}" ]; then
      printf '%s\n' "$1" >VERSION
    elif [ ! -s VERSION ]; then
      is_git_folder || die "no VERSION and no git history here; record the installed version once: make version SET=<commit or release>"
      git rev-parse HEAD >VERSION
    fi
    installed; echo
    ;;
  url)
    to=${1:-main}
    echo "$BASE/compare/$(installed)...$to.diff"
    echo "Open it, save the page as a file, then: make update-from-diff FILE=<saved file> TO=<release or commit>"
    ;;
  download)
    need_target "${1:-}"; to=$1; ver=$(installed)
    command -v curl >/dev/null 2>&1 || die "download needs curl; use make update-url and save the page in a browser"
    mkdir -p .run/updates
    out=.run/updates/$(printf '%s' "$ver" | cut -c1-12)...$to.diff
    curl -fsSL "$BASE/compare/$ver...$to.diff" -o "$out.part" || { rm -f "$out.part"; die "could not fetch $BASE/compare/$ver...$to.diff (HTTPS_PROXY is read from the environment)"; }
    [ -s "$out.part" ] || { rm -f "$out.part"; die "the download is empty: $ver and $to may be the same version"; }
    (check_start "$out.part") || { rm -f "$out.part"; exit 1; }
    mv "$out.part" "$out"
    echo "$out"
    echo "Next: make update-from-diff FILE=$out TO=$to"
    ;;
  apply)
    file=${1:-}; to=${2:-}
    [ -n "$file" ] || die "FILE is missing: make update-from-diff FILE=<saved diff> TO=<release or commit>"
    [ -f "$file" ] || die "FILE $file does not exist"
    [ -s "$file" ] || die "FILE $file is empty"
    need_target "$to"
    ver=$(installed)
    check_start "$file"
    if is_git_folder; then
      git apply --check "$WORK/text.diff" || die "git could not apply the diff"
      git apply --3way "$WORK/text.diff"
    else
      command -v patch >/dev/null 2>&1 || die "this machine has neither git nor patch"
      patch -p1 -s --dry-run <"$WORK/text.diff" >/dev/null || die "patch could not apply the diff; nothing was changed"
      patch -p1 -s <"$WORK/text.diff"
      # BSD patch (macOS) empties a deleted file instead of removing it.
      while read -r p; do rm -f -- "$p"; done <"$WORK/deleted.txt"
    fi
    printf '%s\n' "$to" >VERSION
    echo "Updated from $ver to $to. Run make up: it applies any database migrations."
    if [ -s "$WORK/binary.txt" ]; then
      echo "These binary files are not in a text diff. Download each one and copy it over the installed file:"
      while read -r p; do echo "  $p  $BASE/raw/$to/$p"; done <"$WORK/binary.txt"
    fi
    ;;
  *) die "usage: update_from_diff.sh version [COMMIT] | url [TO] | download TO | apply FILE TO" ;;
esac
