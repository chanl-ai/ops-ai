# Dependency age gate and mirror checks. Every locked version is at least 30 days old because company package mirrors
# block newer ones (docs/architecture/dependencies.md). The mirror targets live here too; every setting a mirror needs is
# in docs/deploy/install.md, "Behind a company mirror".
.PHONY: deps-refresh deps-doctor deps-relock install-mirror qa-mirror mirror-down

##@ Dependencies

AGE_DAYS ?= 30
# The cutoff in pyproject.toml is a fixed date so a lock is reproducible; pnpm's minimumReleaseAge is relative and needs
# no date.
deps-refresh: ## Move the uv age cutoff to today minus 30 days and relock both ecosystems
	@cutoff=$$(python3 -c "import datetime as d; print((d.datetime.now(d.timezone.utc)-d.timedelta(days=$(AGE_DAYS))).strftime('%Y-%m-%dT00:00:00Z'))"); \
	sed -i.bak "s|^exclude-newer = .*|exclude-newer = \"$$cutoff\"|" $(ROOT)/pyproject.toml && rm -f $(ROOT)/pyproject.toml.bak; \
	echo "uv cutoff $$cutoff"
	cd $(ROOT) && uv lock
	cd $(ROOT) && pnpm update -r

deps-doctor: ## Ask the package mirror (UV_DEFAULT_INDEX, NPM_CONFIG_REGISTRY) whether it serves every locked version
	python3 $(ROOT)/scripts/deps_doctor.py

deps-relock: ## Lock again; MIRROR=1 locks within what deps-doctor found the mirror serves, then runs fast tests
ifeq ($(MIRROR),1)
	bash $(ROOT)/scripts/deps_relock.sh
else
	cd $(ROOT) && uv lock && pnpm install --lockfile-only
endif

install-mirror: ## Install the locked Python versions from UV_DEFAULT_INDEX and the npm ones from NPM_CONFIG_REGISTRY
	bash $(ROOT)/scripts/install_via_mirror.sh
	cd $(ROOT) && pnpm install --frozen-lockfile

qa-mirror: ## Nightly lane: clean install through our own Nexus on a network with no other way out, then age, vulnerability and licence checks
	bash $(ROOT)/deploy/mirror-test/lane.sh

mirror-down: ## Stop the lane's Nexus and delete its cache
	bash $(ROOT)/deploy/mirror-test/lane.sh down
