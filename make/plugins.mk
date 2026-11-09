# One pinned list of plugins (deploy/plugins.json) for the image, the laptop and the cloud boxes.
.PHONY: plugins-sync plugins-bump

##@ Plugins

PLUGINS_SYNC_DIR := $(or $(OPS_PLUGINS_DIR),$(STACK_HOME)/plugins)

plugins-sync: ## Put the pinned plugins into OPS_PLUGINS_DIR (default <main checkout>/plugins); PLUGINS_DEV=../ops-ai-plugins links a working copy instead; old contents go to plugins.bak-<date>/
	@PLUGINS_DEV='$(PLUGINS_DEV)' bash $(ROOT)/scripts/plugins_sync.sh '$(PLUGINS_SYNC_DIR)'

plugins-bump: ## Move every pin to the plugins repository's current main (or REF=<branch|tag|sha>) and print old -> new
	@uv run --project $(ROOT) python $(ROOT)/scripts/plugins_bump.py --ref '$(or $(REF),main)'
