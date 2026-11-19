# Update an install from a downloaded GitHub diff, for a team without git access (scripts/update_from_diff.sh;
# docs/deploy/install-guide.md, "Update from a downloaded diff").
.PHONY: version update-url update-download update-from-diff

##@ Update

version: ## Print the installed version, recording it in VERSION from git (or SET=<commit or release>)
	@sh $(ROOT)/scripts/update_from_diff.sh version $(SET)

update-url: ## The GitHub compare page from the installed version to main, or TO=<release tag or commit>
	@sh $(ROOT)/scripts/update_from_diff.sh url $(TO)

update-download: ## Fetch that diff over HTTPS (HTTPS_PROXY honoured) into .run/updates/ and check it: TO=<release tag or commit>
	@sh $(ROOT)/scripts/update_from_diff.sh download "$(TO)"

update-from-diff: ## Apply a saved diff, record the new version: FILE=<path> TO=<release tag or commit>; migrations run on the next make up
	@sh $(ROOT)/scripts/update_from_diff.sh apply "$(FILE)" "$(TO)"
