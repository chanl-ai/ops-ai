#!/usr/bin/env bash
# Brings a persistent export of a git index up to date: scripts/sync-staged-tree.sh <index-file> <tree-dir> <list-file>.
# The tree always equals the index's content (never the working tree). Only paths whose entry (mode, blob, stage) changed
# since the last sync are written, and paths that left the index are deleted; the list file records what the tree holds.
# A missing tree, a missing or damaged list, or an interruption (the list is removed first and written last) falls back to
# a full export, so a half-synced tree is never trusted.
set -euo pipefail
index="$1"; tree="$2"; list="$3"
export GIT_INDEX_FILE="$index"
new="$(mktemp "${TMPDIR:-/tmp}/ops-ai-sync.XXXXXX")"
trap 'rm -f "$new" "$new.old" "$new.add" "$new.del" "$new.del.2" "$new.del.2"' EXIT
# One line per entry, "<mode> <blob> <stage>\t<path>"; -z keeps odd paths intact, then newlines separate the records.
# A path that holds a newline cannot be told apart in this form, so it forces the full export.
git ls-files -s -z | tr '\0' '\n' | LC_ALL=C sort > "$new"
full=0
if [ ! -d "$tree" ] || [ ! -s "$list" ]; then full=1; fi
if [ "$full" = 0 ] && grep -qvE '^[0-7]{6} [0-9a-f]{40,64} [0-3]	' "$list"; then full=1; fi
if [ "$full" = 0 ]; then LC_ALL=C sort "$list" > "$new.old"; fi
rm -f "$list"
if [ "$full" = 1 ]; then
  rm -rf "$tree"; mkdir -p "$tree"
  git checkout-index -a -f --prefix="$tree/"
else
  # Entries only in the new list are written; entries only in the old list whose path is gone are deleted.
  LC_ALL=C comm -13 "$new.old" "$new" | sed 's/^[^	]*	//' > "$new.add"
  LC_ALL=C comm -23 "$new.old" "$new" | sed 's/^[^	]*	//' | LC_ALL=C sort > "$new.del"
  sed 's/^[^	]*	//' "$new" | LC_ALL=C sort | LC_ALL=C comm -13 - "$new.del" > "$new.del.2"
  mv "$new.del.2" "$new.del"
  while IFS= read -r p; do rm -rf "${tree:?}/$p"; done < "$new.del"
  if [ -s "$new.add" ]; then
    # A path that turned from a file into a folder or back is removed first so checkout-index can write it.
    while IFS= read -r p; do if [ -e "$tree/$p" ] || [ -L "$tree/$p" ]; then [ -d "$tree/$p" ] && [ ! -L "$tree/$p" ] && rm -rf "${tree:?}/$p"; fi; done < "$new.add"
    tr '\n' '\0' < "$new.add" | git checkout-index -f -z --prefix="$tree/" --stdin
  fi
fi
cp "$new" "$list.tmp.$$" && mv "$list.tmp.$$" "$list"
