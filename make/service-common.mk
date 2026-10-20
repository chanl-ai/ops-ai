# Included by every service Makefile (not by the root): the shared env and the verbs that act on the background
# process `make up` started. A service Makefile sets STACK_SVC (agents, tools, console) before including this.
SERVICE_COMMON := $(lastword $(MAKEFILE_LIST))
include $(dir $(SERVICE_COMMON))env.mk
.DEFAULT_GOAL := help
.PHONY: help stop logs health

help: ## List this Makefile's targets
	@awk "$$HELP_AWK" $(firstword $(MAKEFILE_LIST))
	@printf '\nBackground process (from make up)\n'
	@awk "$$HELP_AWK" $(SERVICE_COMMON)

stop: ## Stop the background process `make up` started
	@$(STACK) stop $(STACK_SVC)

logs: ## Follow the background process's log (FOLLOW=0 to print and exit)
	@OPS_LOGS_FOLLOW=$(if $(FOLLOW),$(FOLLOW),1) $(STACK) logs $(STACK_SVC)

health: ## Probe this service
	@$(STACK) health $(STACK_SVC)
