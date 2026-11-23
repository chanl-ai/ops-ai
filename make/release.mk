# The release package a client team installs from (docs/deploy/release-package.md): images for linux/amd64 saved as one
# bundle, compose files, the env template, PostgreSQL and Azure SQL scripts and the install guide, from `git archive TAG`.
.PHONY: release-package release-proof install-proof release-tag release-main release-cut release-pr release-version hotfix-cut

##@ Release

release-package: ## dist/ops-ai-<version>/, its tarball, the image bundle and SHA256SUMS (TAG=<ref>; IMAGE_PREFIX, BUILD=0)
	@test -n "$(TAG)" || { echo "release-package: set TAG to a tag or commit"; exit 2; }
	sh $(ROOT)/deploy/release/package.sh "$(TAG)"

release-proof: ## Install a package from its tarball alone and walk it (PACKAGE=dist/ops-ai-<version>.tar.gz)
	@test -n "$(PACKAGE)" || { echo "release-proof: set PACKAGE to dist/ops-ai-<version>.tar.gz"; exit 2; }
	sh $(ROOT)/deploy/release/proof.sh "$(PACKAGE)"

release-tag: ## Tag the develop commit of a merged `release: X.Y.Z into develop` (or hotfix) PR vX.Y.Z and push it (REF, REMOTE=origin, VERSION; DRY=1 prints the name)
	sh $(ROOT)/scripts/release-tag.sh

release-cut: ## After a release landed: fast-forward release/current to origin/develop, or create it (DRY=1 is the default, DRY=0 pushes)
	DRY=$(or $(DRY),1) python3 $(ROOT)/scripts/release.py cut

hotfix-cut: ## hotfix/<what> from the newest vX.Y.Z tag (FROM=<tag>), version file set to V (V=X.Y.Z HOTFIX=<what>; DRY=0 pushes)
	DRY=$(or $(DRY),1) python3 $(ROOT)/scripts/release.py hotfix-cut

release-version: ## One commit on release/current (or hotfix/<what>) that sets deploy/release/version to V (V=X.Y.Z; HOTFIX=<what>; DRY=0 pushes)
	DRY=$(or $(DRY),1) python3 $(ROOT)/scripts/release.py set-version

release-pr: ## PR release/current into develop titled `release: V into develop`; refuses unless develop is merged in, the version file says V and make ci-local is green on the head (V=X.Y.Z; HOTFIX=<what> for a hotfix; DRY=1 prints, DRY=0 opens)
	DRY=$(or $(DRY),1) python3 $(ROOT)/scripts/release.py pr

release-main: ## Fast-forward main to a tagged develop commit with a plain push, never forced (REF=<commit>, REMOTE=origin; DRY=1 prints)
	sh $(ROOT)/scripts/release-main.sh

install-proof: ## A fresh clone, ./install.sh on images pulled from GHCR, walk, rerun, upgrade, backup, restore, DBA mode (SOURCE, REF; BUILD=1 builds the commit's images into a local registry first)
	BUILD=$(or $(BUILD),0) bash $(ROOT)/deploy/release/install_proof.sh "$(or $(SOURCE),$(ROOT))" "$(or $(REF),HEAD)"
