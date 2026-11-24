# One pinned list of plugins (deploy/plugins.json) for the image, the laptop and the cloud boxes.
.PHONY: plugins-sync plugins-check plugins-bump s3-test-store

##@ Plugins

PLUGINS_SYNC_DIR := $(or $(OPS_PLUGINS_DIR),$(STACK_HOME)/plugins)

plugins-sync: ## Put the pinned plugins into OPS_PLUGINS_DIR (default <main checkout>/plugins); PLUGINS_DEV=../ops-ai-plugins links a working copy instead; old contents go to plugins.bak-<date>/
	@PLUGINS_DEV='$(PLUGINS_DEV)' bash $(ROOT)/scripts/plugins_sync.sh '$(PLUGINS_SYNC_DIR)'

plugins-check: ## Say whether the plugins folder the stack reads matches deploy/plugins.json, and print the fix when not (make up and make restart run it)
	@bash $(ROOT)/scripts/plugins_check.sh '$(PLUGINS_SYNC_DIR)'

plugins-bump: ## Move every pin to the plugins repository's current main (or REF=<branch|tag|sha>) and print old -> new
	@uv run --project $(ROOT) python $(ROOT)/scripts/plugins_bump.py --ref '$(or $(REF),main)'

# The S3 plugin's tests (test_s3_source.py, test_request_signing.py) skip without an S3-compatible store; CI starts this
# one for them. SeaweedFS 4.55 answers the S3 API and checks every signature. `-volume.max=0` lets it make a volume per
# bucket, without which writes fail after a few buckets with "No writable volumes". A stopped store is started again
# with its buckets, so a second run reuses the container and its key file under .data/.
S3_TEST_IMAGE ?= chrislusf/seaweedfs@sha256:7ca46aeae2f223b37e5d91593c17ab37738eec6df6ab69b48a0487f7643342b9
S3_TEST_PORT ?= 19000
S3_TEST_NAME := ops-s3-test
S3_TEST_DIR := $(ROOT)/.data/s3-test

s3-test-store: ## Start a local S3-compatible store (SeaweedFS in Docker) on S3_TEST_PORT, wait until it answers, and print the OPS_TEST_S3_* variables; S3_TEST_STOP=1 stops it
	@if [ -n "$(S3_TEST_STOP)" ]; then docker stop $(S3_TEST_NAME) >/dev/null && echo "stopped $(S3_TEST_NAME)"; exit 0; fi; \
	mkdir -p '$(S3_TEST_DIR)'; \
	printf '%s' '{"identities":[{"name":"test","credentials":[{"accessKey":"opsai-test","secretKey":"opsai-test-secret"}],"actions":["Admin","Read","List","Tagging","Write"]}]}' > '$(S3_TEST_DIR)/s3.json'; \
	docker start $(S3_TEST_NAME) >/dev/null 2>&1 || docker run -d --name $(S3_TEST_NAME) -p 127.0.0.1:$(S3_TEST_PORT):8333 \
	  -v '$(S3_TEST_DIR)':/etc/s3:ro $(S3_TEST_IMAGE) \
	  server -s3 -s3.config=/etc/s3/s3.json -dir=/data -volume.max=0 -master.volumeSizeLimitMB=16 >/dev/null; \
	for i in $$(seq 1 60); do curl -s -o /dev/null http://127.0.0.1:$(S3_TEST_PORT)/ && break; sleep 1; done; \
	curl -s -o /dev/null http://127.0.0.1:$(S3_TEST_PORT)/ || { echo "the S3 test store did not answer"; docker logs --tail 20 $(S3_TEST_NAME); exit 1; }; \
	echo "OPS_TEST_S3_URL=http://127.0.0.1:$(S3_TEST_PORT) OPS_TEST_S3_KEY=opsai-test OPS_TEST_S3_SECRET=opsai-test-secret"
