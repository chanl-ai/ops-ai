# Per-service pass-throughs, generated: <verb>-<svc> runs `make -C <svc dir> <verb>`. Add a service by adding it to
# SERVICES and SVC_DIR_<svc>; every service Makefile implements SERVICE_VERBS (planned ones answer "not started").
SERVICES := agents tools models platform console
PLANNED_SERVICES := hitl-service kb-service files-service
SVC_DIR_agents := services/agents-service
SVC_DIR_tools := services/tools-service
SVC_DIR_models := services/models-service
SVC_DIR_platform := services/platform-service
SVC_DIR_console := apps/console
SERVICE_VERBS := install run stop test lint typecheck verify migrate logs health clean

define service_target
.PHONY: $(1)-$(2)
$(1)-$(2):
	$$(MAKE) -C $$(SVC_DIR_$(2)) $(1)
endef

$(foreach s,$(SERVICES),$(foreach v,$(SERVICE_VERBS),$(eval $(call service_target,$(v),$(s)))))
