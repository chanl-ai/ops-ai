# make setup (c-545): asks what a person has, tests each answer live, and writes settings only for what passed
# (scripts/setup/, docs/deploy/install.md "Set up with make setup"). It runs before make install: every check is the
# standard library except the database driver, so it uses the workspace's Python when there is one and python3 if not.
.PHONY: setup skills-proof

##@ Setup

SETUP_PYTHON = $(if $(wildcard $(ROOT)/.venv/bin/python),$(ROOT)/.venv/bin/python,python3)

setup: ## Ask what this machine has, test each answer live and write what passed (ANSWERS=<file> asks nothing; SETUP_FILE=<path> writes elsewhere)
	@PYTHONPATH=$(ROOT)/scripts:$(ROOT)/deploy/database $(SETUP_PYTHON) -m setup $(if $(ANSWERS),--answers $(ANSWERS))

skills-proof: ## Run every developer skill's proof block (docs/guide/skills/) in a fresh devcontainer, PASS/FAIL per skill (SKILLS="ops-run ..." for some, KEEP=1 leaves it up)
	@SKILLS="$(SKILLS)" bash $(ROOT)/scripts/skills_proof.sh
