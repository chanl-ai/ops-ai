# The release package a client team installs from (docs/deploy/release-package.md): images for linux/amd64 saved as one
# bundle, compose files, the env template, PostgreSQL and Azure SQL scripts and the install guide, from `git archive TAG`.
.PHONY: release-package release-proof install-proof release-start hotfix-start release-rc release-doctor

##@ Release

release-package: ## dist/ops-ai-<version>/, its tarball, the image bundle and SHA256SUMS (TAG=<ref>; IMAGE_PREFIX, BUILD=0)
	@test -n "$(TAG)" || { echo "release-package: set TAG to a tag or commit"; exit 2; }
	sh $(ROOT)/deploy/release/package.sh "$(TAG)"

release-proof: ## Install a package from its tarball alone and walk it (PACKAGE=dist/ops-ai-<version>.tar.gz)
	@test -n "$(PACKAGE)" || { echo "release-proof: set PACKAGE to dist/ops-ai-<version>.tar.gz"; exit 2; }
	sh $(ROOT)/deploy/release/proof.sh "$(PACKAGE)"

release-start: ## release/V from origin/develop with one version commit and a PR into main (V=X.Y.Z; DRY=1 prints, DRY=0 pushes and opens)
	DRY=$(or $(DRY),1) python3 $(ROOT)/scripts/release.py start

hotfix-start: ## hotfix/NAME from the newest vX.Y.Z tag with one version commit and a PR into main (V=X.Y.Z NAME=<what>; DRY=0 pushes and opens)
	DRY=$(or $(DRY),1) python3 $(ROOT)/scripts/release.py hotfix-start

release-rc: ## Tag the release or hotfix branch's tip vX.Y.Z-rc.N once its staging deploy and walk passed (DRY=0 pushes the tag)
	DRY=$(or $(DRY),1) python3 $(ROOT)/scripts/release.py rc

release-doctor: ## Check the release flow is one path: stale mentions, matching versions, the docs' targets (LIVE=1 also reads GitHub: branches, tags, merge-back)
	python3 $(ROOT)/scripts/release_doctor.py $(if $(LIVE),--live)

install-proof: ## A fresh clone, ./install.sh on images pulled from GHCR, walk, rerun, upgrade, backup, restore, DBA mode (SOURCE, REF; BUILD=1 builds the commit's images into a local registry first)
	BUILD=$(or $(BUILD),0) bash $(ROOT)/deploy/release/install_proof.sh "$(or $(SOURCE),$(ROOT))" "$(or $(REF),HEAD)"
