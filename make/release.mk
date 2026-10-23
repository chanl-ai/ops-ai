# The release package a client team installs from (docs/deploy/release-package.md): images for linux/amd64 saved as one
# bundle, compose files, the env template, PostgreSQL and Azure SQL scripts and the install guide, from `git archive TAG`.
.PHONY: release-package release-proof install-proof release-tag

##@ Release

release-package: ## dist/ops-ai-<version>/, its tarball, the image bundle and SHA256SUMS (TAG=<ref>; IMAGE_PREFIX, BUILD=0)
	@test -n "$(TAG)" || { echo "release-package: set TAG to a tag or commit"; exit 2; }
	sh $(ROOT)/deploy/release/package.sh "$(TAG)"

release-proof: ## Install a package from its tarball alone and walk it (PACKAGE=dist/ops-ai-<version>.tar.gz)
	@test -n "$(PACKAGE)" || { echo "release-proof: set PACKAGE to dist/ops-ai-<version>.tar.gz"; exit 2; }
	sh $(ROOT)/deploy/release/proof.sh "$(PACKAGE)"

release-tag: ## Tag the merged commit vYYYY-MM-DD.N and push it (REF, REMOTE=origin; DRY=1 prints the name)
	sh $(ROOT)/scripts/release-tag.sh

install-proof: ## A fresh clone, ./install.sh on images pulled from GHCR, walk, rerun, upgrade, backup, restore, DBA mode (SOURCE, REF)
	bash $(ROOT)/deploy/release/install_proof.sh "$(or $(SOURCE),$(ROOT))" "$(or $(REF),HEAD)"
