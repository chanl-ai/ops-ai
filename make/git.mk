# Git in commands a person can read: commit named files with the checks, and lanes (worktrees) for parallel work.
# scripts/git-rules.py refuses only what loses work or skips review (stash, hard reset, clean, --no-verify, pushes to main).
#
#   make commit FILES='a.py b.md' MSG='fix(tools): fill query placeholders' CHANGELOG=query-placeholders [BODY='why; what ran']
#   make unstage FILES='a.py'          take files out of the shared index, keeping every line in the working tree
#   make whats-mine FILES='a.py'       show what would be committed for these files, against HEAD
#   make git-rules                     list the rules and check them

#   make my-hunks FILE=docs/usecases/README.md > mine.patch     then delete the hunks that are not yours
#   make commit-hunks PATCH=mine.patch MSG='docs(x): add uc-588 row' CHANGELOG=plugin-sign-in

.PHONY: commit unstage whats-mine git-rules my-hunks commit-hunks

my-hunks: ## Print FILE's changes against HEAD as a patch, to keep only your own hunks before commit-hunks
	@[ -n "$(FILE)" ] || { echo "make my-hunks: name the file, e.g. FILE='docs/usecases/README.md'" >&2; exit 2; }
	@git diff HEAD -- $(FILE)

commit-hunks: ## Commit only the hunks in PATCH onto HEAD (for shared files), with MSG (and CHANGELOG, BODY)
	@[ -n "$(PATCH)" ] || { echo "make commit-hunks: give the patch, e.g. PATCH=mine.patch"; exit 2; }
	@[ -n "$(MSG)" ] || { echo "make commit-hunks: give a subject, e.g. MSG='docs(x): add a row'"; exit 2; }
	@msg=$$(mktemp "$${TMPDIR:-/tmp}/commit-msg.XXXXXX"); \
	  printf '%s\n' "$(MSG)" > "$$msg"; \
	  if [ -n "$(BODY)" ]; then printf '\n%s\n' "$(BODY)" >> "$$msg"; fi; \
	  if [ -n "$(CHANGELOG)" ]; then printf '\nChangelog: %s\n' "$(CHANGELOG)" >> "$$msg"; fi; \
	  bash scripts/commit-patch.sh "$$msg" "$(PATCH)"; rc=$$?; rm -f "$$msg"; exit $$rc

commit: ## Commit only FILES, with MSG (and CHANGELOG, BODY), through both hooks, from HEAD plus those files
	@[ -n "$(FILES)" ] || { echo "make commit: name your files, e.g. FILES='services/x/a.py'"; exit 2; }
	@[ -n "$(MSG)" ] || { echo "make commit: give a subject, e.g. MSG='fix(tools): fill query placeholders'"; exit 2; }
	@# The named Python files are linted and formatted as the gate will see them (named paths, so examples/ too), which
	@# is what refused most commits; NOFIX=1 leaves them as they are. The gate itself is unchanged.
	@if [ -z "$(NOFIX)" ]; then py=$$(for f in $(FILES); do [ -f "$$f" ] && echo "$$f"; done | grep '\.py$$'); \
	  if [ -n "$$py" ]; then $(ROOT)/.venv/bin/ruff check --fix --quiet $$py || true; $(ROOT)/.venv/bin/ruff format --quiet $$py; fi; fi
	@msg=$$(mktemp "$${TMPDIR:-/tmp}/commit-msg.XXXXXX"); \
	  printf '%s\n' "$(MSG)" > "$$msg"; \
	  if [ -n "$(BODY)" ]; then printf '\n%s\n' "$(BODY)" >> "$$msg"; fi; \
	  if [ -n "$(CHANGELOG)" ]; then printf '\nChangelog: %s\n' "$(CHANGELOG)" >> "$$msg"; fi; \
	  bash scripts/commit-paths.sh "$$msg" $(FILES); rc=$$?; rm -f "$$msg"; exit $$rc

unstage: ## Take FILES out of the shared index; the working files keep every line
	@[ -n "$(FILES)" ] || { echo "make unstage: name the files, e.g. FILES='a.py'"; exit 2; }
	@git restore --staged -- $(FILES) && echo "unstaged: $(FILES)"

whats-mine: ## Show what `make commit FILES=…` would commit, against HEAD
	@[ -n "$(FILES)" ] || { echo "make whats-mine: name the files, e.g. FILES='a.py'"; exit 2; }
	@git status --short -- $(FILES); git diff HEAD --stat -- $(FILES); git diff HEAD -- $(FILES)

git-rules: ## Print the git rules for the shared tree and check them
	@python3 -c "import importlib.util as u; s=u.spec_from_file_location('r','scripts/git-rules.py'); m=u.module_from_spec(s); s.loader.exec_module(m); [print('-', w, '\n  instead:', i) for _, w, i in m.RULES]"
	@python3 scripts/git-rules.py --self-test

# Lanes: worktrees beside this checkout, one per area, each on its own branch, ports and database (scripts/lane.sh).
#   make lane NAME=backend N=1       ../ops-ai-lane-backend on a fresh branch from origin/main, ports +1000
#   make lanes                       every lane: number, branch, stack up or down, last commit, PR
#   make lane-next BRANCH=feat/api-own-account-run [BASE=feat/x]   inside a lane: start the next card
#   make lane-rm NAME=backend        remove a lane whose work is pushed
.PHONY: lane lanes lane-next lane-rm

lane: ## Make a lane worktree NAME on ports +N×1000 (N 1-5)
	@bash scripts/lane.sh add "$(NAME)" "$(N)" $(BASE)

lanes: ## List the main checkout and every lane: branch, stack, last commit, PR
	@bash scripts/lane.sh list

lane-next: ## Inside a lane: start the next card on BRANCH from origin/main (or BASE), migrating the lane's database
	@bash scripts/lane.sh next "$(BRANCH)" $(BASE)

lane-rm: ## Remove lane NAME once its work is pushed
	@bash scripts/lane.sh remove "$(NAME)"
