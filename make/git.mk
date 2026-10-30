# Git for the shared tree, in commands a person can read. Several builders edit one working tree, so these touch only
# the files named; the raw git commands that would touch everyone's work are refused by scripts/git-rules.py.
#
#   make commit FILES='a.py b.md' MSG='fix(tools): fill query placeholders' CARD=c-586 [BODY='why; what ran']
#   make unstage FILES='a.py'          take files out of the shared index, keeping every line in the working tree
#   make whats-mine FILES='a.py'       show what would be committed for these files, against HEAD
#   make git-rules                     list the rules and check them

.PHONY: commit unstage whats-mine git-rules

commit: ## Commit only FILES, with MSG (and CARD, BODY), through both hooks, from HEAD plus those files
	@[ -n "$(FILES)" ] || { echo "make commit: name your files, e.g. FILES='services/x/a.py'"; exit 2; }
	@[ -n "$(MSG)" ] || { echo "make commit: give a subject, e.g. MSG='fix(tools): fill query placeholders'"; exit 2; }
	@msg=$$(mktemp "$${TMPDIR:-/tmp}/commit-msg.XXXXXX"); \
	  printf '%s\n' "$(MSG)" > "$$msg"; \
	  if [ -n "$(BODY)" ]; then printf '\n%s\n' "$(BODY)" >> "$$msg"; fi; \
	  if [ -n "$(CARD)" ]; then printf '\nCard: %s\n' "$(CARD)" >> "$$msg"; fi; \
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
