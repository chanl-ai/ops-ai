# Git in commands a person can read: commit named files with the checks, and review a branch on the one stack.
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

# One checkout, one stack: a branch is reviewed by checking it out here and restarting on it, so what runs on the
# usual ports (console :3016) is always the branch checked out.
#   make review BRANCH=feat/apps-salesforce
.PHONY: review

review: ## Check out BRANCH from origin and restart the stack on it, migrating each service first; refuses with uncommitted work
	@[ -n "$(BRANCH)" ] || { echo "make review: name the branch, e.g. BRANCH=feat/apps-salesforce"; exit 2; }
	@[ -z "$$(git status --porcelain --untracked-files=no)" ] || { echo "make review: commit or move your changes first; a branch switch would carry them onto $(BRANCH)"; exit 1; }
	git fetch origin "$(BRANCH)"
	git switch "$(BRANCH)" 2>/dev/null || git switch --track "origin/$(BRANCH)"
	git merge --ff-only "origin/$(BRANCH)"
	$(MAKE) restart
