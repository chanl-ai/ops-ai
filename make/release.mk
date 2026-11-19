# The release package a client team installs from (docs/deploy/release-package.md): images for linux/amd64 saved as one
# bundle, compose files, the env template, PostgreSQL and Azure SQL scripts and the install guide, from `git archive TAG`.
.PHONY: release-package release-proof install-proof release-tag release-cut release-pr release-back-merge hotfix-cut

##@ Release

release-package: ## dist/ops-ai-<version>/, its tarball, the image bundle and SHA256SUMS (TAG=<ref>; IMAGE_PREFIX, BUILD=0)
	@test -n "$(TAG)" || { echo "release-package: set TAG to a tag or commit"; exit 2; }
	sh $(ROOT)/deploy/release/package.sh "$(TAG)"

release-proof: ## Install a package from its tarball alone and walk it (PACKAGE=dist/ops-ai-<version>.tar.gz)
	@test -n "$(PACKAGE)" || { echo "release-proof: set PACKAGE to dist/ops-ai-<version>.tar.gz"; exit 2; }
	sh $(ROOT)/deploy/release/proof.sh "$(PACKAGE)"

release-tag: ## Tag a merged release or hotfix commit vX.Y.Z and push it (REF, REMOTE=origin, VERSION; DRY=1 prints the name)
	sh $(ROOT)/scripts/release-tag.sh

release-cut: ## Cut release/V from origin/develop and push it; the push deploys it to staging (V=X.Y.Z; DRY=1 is the default, DRY=0 pushes)
	DRY=$(or $(DRY),1) python3 $(ROOT)/scripts/release.py cut

hotfix-cut: ## Cut hotfix/V from origin/main and push it; the push deploys it to staging (V=X.Y.Z; DRY=1 is the default, DRY=0 pushes)
	DRY=$(or $(DRY),1) python3 $(ROOT)/scripts/release.py hotfix-cut

release-pr: ## PR release/V (or hotfix/V) into main; refuses unless CI and the staging deploy with its click walk succeeded on its head (V=X.Y.Z; DRY=1 prints, DRY=0 opens)
	DRY=$(or $(DRY),1) python3 $(ROOT)/scripts/release.py pr

release-back-merge: ## PR main into develop once the tag vV is on main (V=X.Y.Z; DRY=1 prints, DRY=0 opens)
	DRY=$(or $(DRY),1) python3 $(ROOT)/scripts/release.py back-merge

install-proof: ## A fresh clone, ./install.sh on images pulled from GHCR, walk, rerun, upgrade, backup, restore, DBA mode (SOURCE, REF; BUILD=1 builds the commit's images into a local registry first)
	BUILD=$(or $(BUILD),0) bash $(ROOT)/deploy/release/install_proof.sh "$(or $(SOURCE),$(ROOT))" "$(or $(REF),HEAD)"
