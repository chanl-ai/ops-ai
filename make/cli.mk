# Ops AI from the terminal, through the `ops` command (sdk/python): every target calls the routes the console calls,
# signed in through the password sign-in as AS= (a dev role, a seeded person's name such as james, or an email), with
# X-Team-Id for TEAM= or the person's own team. JSON=1 prints JSON. The session is kept in .run/api-tokens, the file
# `make api` keeps, so the two share one sign-in per person. What a target makes carries the `[test] ` prefix (a dev
# seed sign-in is a test run), so `make test-data-clean` finds it.

OPS_CLI = uv run --quiet --project $(ROOT)/sdk/python ops
# The options go before the verb, where every area reads them.
OPS_AS = --as '$(AS)' $(if $(TEAM),--team $(TEAM)) $(if $(JSON),--json)
# $(call need,VAR,example): stops the target with what to give when VAR is empty.
need = $(if $($(1)),,$(error make $@: give $(1)=, e.g. $(2)))

.PHONY: demo-org-seed demo-org-remove chat chat-script assistant-evals chat-show chat-calls chat-agents chat-accounts chat-kbs chat-threads chat-connected \
	chat-approve chat-reject chat-submit chat-transcript chat-transcripts \
	kb-bases kb-show kb-documents kb-sources kb-source kb-items kb-add-file kb-add-text kb-sync kb-search kb-changes \
	kb-change \
	apps-list apps-show apps-on apps-add-tool apps-accounts apps-mine apps-connect apps-test apps-auth-configs \
	tools-list tools-show tools-run tools-calls tools-call \
	runs-list runs-start runs-show runs-events runs-cancel runs-retry tasks-list tasks-show tasks-decide \
	cases-list cases-show cases-note files-list files-show files-upload documents-types documents-type \
	documents-extractions people-list people-invite people-roles people-me \
	models-aliases models-providers models-keys models-test memories-list memories-forget memories-forget-agent \
	memories-export test-data-clean

##@ Chat (ops chat)

chat: ## make chat AS=james AGENT='Case helper' SAY='…' [THREAD=th_…] [TEST=1] [KB=kb_…] [CONNECTED=Salesforce]: chat turns streamed, tool calls and the call log printed
	@$(if $(SAY)$(CONNECTED),,echo "make chat: give SAY='…' or CONNECTED=<app>" >&2; exit 2)
	@$(OPS_CLI) chat $(OPS_AS) say $(if $(AGENT),--agent '$(AGENT)') $(if $(THREAD),--thread $(THREAD)) $(if $(TEST),--test) \
		$(if $(KB),--kb $(KB)) $(if $(SAY),-m '$(SAY)') $(if $(CONNECTED),--connected '$(CONNECTED)')
chat-script: ## make chat-script FILE=docs/usecases/chat/<x>.yaml AS=james: a scripted conversation, PASS or FAIL per turn
	$(call need,FILE,FILE=docs/usecases/chat/salesforce-case-helper.yaml)
	@$(OPS_CLI) chat $(OPS_AS) script '$(FILE)'
# The real-model subset moves only the assistant's alias, on its own provider connection, to a real model and back,
# so memory and every other alias stay on the fake (scripts/demo_model.py PROVIDER=).
ASSISTANT_ALIAS ?= assistant
ASSISTANT_PROVIDER ?= assistant-model
REAL_MODEL ?= gpt-5.5
# The effort the real binding sends; none by default, as gpt-5.5 refuses function tools with any effort on chat
# completions ("Function tools with reasoning_effort are not supported").
REAL_EFFORT ?=
MAX_CALLS ?= 10
assistant-evals: ## make assistant-evals [REAL=1] [ONLY='a b']: the team assistant's scripted chats (docs/usecases/chat/assistant/) as each script's people, with a scorecard; REAL=1 runs the real subset on ASSISTANT_ALIAS bound to REAL_MODEL, at most MAX_CALLS model calls
	@$(if $(REAL),$(MAKE) -s demo-model ALIAS=$(ASSISTANT_ALIAS) PROVIDER=$(ASSISTANT_PROVIDER) MODEL=$(REAL_MODEL) EFFORT=$(REAL_EFFORT) &&) \
	$(OPS_CLI) chat $(OPS_AS) evals docs/usecases/chat/assistant $(if $(REAL),--real --max-calls $(MAX_CALLS)) $(foreach s,$(ONLY),--only $(s)); status=$$?; \
	$(if $(REAL),$(MAKE) -s demo-model ALIAS=$(ASSISTANT_ALIAS) PROVIDER=$(ASSISTANT_PROVIDER) MODEL=fake;) exit $$status
chat-show: ## make chat-show THREAD=th_… AS=james: the conversation as the chat reads it
	$(call need,THREAD,THREAD=th_…)
	@$(OPS_CLI) chat $(OPS_AS) show $(THREAD)
chat-calls: ## make chat-calls THREAD=th_… AS=james: the conversation's tool-call log, whose sign-in each used
	$(call need,THREAD,THREAD=th_…)
	@$(OPS_CLI) chat $(OPS_AS) calls $(THREAD)
chat-agents: ## make chat-agents AS=james: the agents New chat offers
	@$(OPS_CLI) chat $(OPS_AS) agents
chat-threads: ## make chat-threads AS=james [SEARCH=]: your conversations, newest first
	@$(OPS_CLI) chat $(OPS_AS) threads $(if $(SEARCH),--search '$(SEARCH)')
chat-accounts: ## make chat-accounts AS=james: My accounts, the sign-ins the chat uses as you
	@$(OPS_CLI) apps $(OPS_AS) mine
chat-kbs: ## make chat-kbs AS=james: the knowledge bases a chat may answer from
	@$(OPS_CLI) kb $(OPS_AS) bases
chat-transcript: ## make chat-transcript THREAD=th_… AS=james [ALL=1]: the conversation as Markdown to paste (the last turn; ALL=1 every turn)
	$(call need,THREAD,THREAD=th_…)
	@$(OPS_CLI) chat $(OPS_AS) transcript --thread $(THREAD) $(if $(ALL),--all-turns)
chat-transcripts: ## make chat-transcripts AS=james [SEARCH='[test]'] [ALL=1]: a transcript of each of the person's chats whose title holds SEARCH
	@$(OPS_CLI) chat $(OPS_AS) transcripts $(if $(SEARCH),--search '$(SEARCH)') $(if $(ALL),--all-turns)
chat-connected: ## make chat-connected THREAD=th_… [APP=Salesforce] AS=james: the Connect card's follow-up once signed in
	$(call need,THREAD,THREAD=th_…)
	@$(OPS_CLI) chat $(OPS_AS) connected $(THREAD) $(if $(APP),'$(APP)')
chat-approve: ## make chat-approve THREAD=th_… [WIDGET=] AS=approver: approve the newest open widget, or WIDGET=
	$(call need,THREAD,THREAD=th_…)
	@$(OPS_CLI) chat $(OPS_AS) approve $(THREAD) $(WIDGET)
chat-reject: ## make chat-reject THREAD=th_… REASON='…' [WIDGET=] AS=approver: reject a widget with a reason
	$(call need,THREAD,THREAD=th_…)
	$(call need,REASON,REASON='Wrong account')
	@$(OPS_CLI) chat $(OPS_AS) reject $(THREAD) $(WIDGET) --reason '$(REASON)'
chat-submit: ## make chat-submit THREAD=th_… VALUES='a=1 b=2' [WIDGET=] AS=james: submit a form widget
	$(call need,THREAD,THREAD=th_…)
	@$(OPS_CLI) chat $(OPS_AS) submit $(THREAD) $(WIDGET) $(foreach v,$(VALUES),--value '$(v)')

##@ Knowledge (ops kb)

kb-bases: ## make kb-bases AS=james [SEARCH=]: the knowledge bases
	@$(OPS_CLI) kb $(OPS_AS) bases $(if $(SEARCH),--search '$(SEARCH)')
kb-show: ## make kb-show KB=kb_… AS=james: one knowledge base
	$(call need,KB,KB=kb_retail_products)
	@$(OPS_CLI) kb $(OPS_AS) show $(KB)
kb-documents: ## make kb-documents KB=kb_… AS=james: a knowledge base's documents
	$(call need,KB,KB=kb_retail_products)
	@$(OPS_CLI) kb $(OPS_AS) documents $(KB) $(if $(SEARCH),--search '$(SEARCH)')
kb-sources: ## make kb-sources AS=james: the sources
	@$(OPS_CLI) kb $(OPS_AS) sources $(if $(SEARCH),--search '$(SEARCH)')
kb-source: ## make kb-source SRC=src_… AS=james: one source
	$(call need,SRC,SRC=src_…)
	@$(OPS_CLI) kb $(OPS_AS) source $(SRC)
kb-items: ## make kb-items SRC=src_… AS=james: a source's items
	$(call need,SRC,SRC=src_…)
	@$(OPS_CLI) kb $(OPS_AS) items $(SRC)
kb-add-file: ## make kb-add-file KB=kb_… FILE=path AS=james: upload a file into a knowledge base and sync it
	$(call need,KB,KB=kb_…)
	$(call need,FILE,FILE=docs/policy.pdf)
	@$(OPS_CLI) kb $(OPS_AS) add-file $(KB) '$(FILE)'
kb-add-text: ## make kb-add-text KB=kb_… TITLE='…' TEXT='…' AS=james: a written page (TEXT=@file reads a file)
	$(call need,KB,KB=kb_…)
	$(call need,TITLE,TITLE='Overdraft fees')
	@$(OPS_CLI) kb $(OPS_AS) add-text $(KB) --title '$(TITLE)' --text '$(TEXT)'
kb-sync: ## make kb-sync SRC=src_…|KB=kb_… [FULL=1] AS=james: sync a source, or every source of a knowledge base
	@$(if $(SRC)$(KB),,echo "make kb-sync: give SRC= or KB=" >&2; exit 2)
	@$(OPS_CLI) kb $(OPS_AS) sync $(or $(SRC),$(KB)) $(if $(FULL),--full)
kb-search: ## make kb-search KB=kb_… TEXT='…' AS=james: ask a knowledge base, as its Playground tab does
	$(call need,KB,KB=kb_retail_products)
	$(call need,TEXT,TEXT='What is the overdraft fee?')
	@$(OPS_CLI) kb $(OPS_AS) search $(KB) '$(TEXT)'
kb-changes: ## make kb-changes [KB=kb_…] AS=james: knowledge changes waiting on review
	@$(OPS_CLI) kb $(OPS_AS) changes $(if $(KB),--kb $(KB))
kb-change: ## make kb-change ID=… AS=james: one knowledge change
	$(call need,ID,ID=chg_…)
	@$(OPS_CLI) kb $(OPS_AS) change $(ID)

##@ Apps and connections (ops apps)

apps-list: ## make apps-list AS=admin [CONNECTED=1]: the Apps page's cards
	@$(OPS_CLI) apps $(OPS_AS) list $(if $(CONNECTED),--connected)
apps-show: ## make apps-show APP=plugin:opsai.salesforce AS=james: one app's page data
	$(call need,APP,APP=plugin:opsai.salesforce)
	@$(OPS_CLI) apps $(OPS_AS) show '$(APP)'
apps-add-tool: ## make apps-add-tool APP=… TOOL='a b' AS=builder: add the app's tools to the team
	$(call need,APP,APP=plugin:opsai.github)
	$(call need,TOOL,TOOL=github_get_issue)
	@$(OPS_CLI) apps $(OPS_AS) add-tool '$(APP)' $(TOOL)
apps-on: ## make apps-on APP=… [PLACE=] [WHOSE=each|team|person] [NO_ASSISTANT=1] AS=admin: turn an app on, print its sign-in link
	$(call need,APP,APP=plugin:opsai.salesforce)
	@$(OPS_CLI) apps $(OPS_AS) on '$(APP)' $(if $(PLACE),--place '$(PLACE)') $(if $(WHOSE),--whose $(WHOSE)) $(if $(NO_ASSISTANT),--no-assistant)
apps-accounts: ## make apps-accounts APP=… AS=admin: an app's accounts
	$(call need,APP,APP=plugin:opsai.salesforce)
	@$(OPS_CLI) apps $(OPS_AS) accounts '$(APP)'
apps-mine: ## make apps-mine AS=james: My accounts
	@$(OPS_CLI) apps $(OPS_AS) mine
apps-connect: ## make apps-connect APP=… [ACCOUNT=] [TEAM_ACCOUNT=1] AS=james: print the sign-in link that connects an account
	$(call need,APP,APP=plugin:opsai.salesforce)
	@$(OPS_CLI) apps $(OPS_AS) connect '$(APP)' $(if $(ACCOUNT),--account $(ACCOUNT)) $(if $(TEAM_ACCOUNT),--team-account)
apps-test: ## make apps-test APP=… [ACCOUNT=] [TEAM_ACCOUNT=1] AS=admin: test an account
	$(call need,APP,APP=plugin:opsai.salesforce)
	@$(OPS_CLI) apps $(OPS_AS) test '$(APP)' $(if $(ACCOUNT),--account $(ACCOUNT)) $(if $(TEAM_ACCOUNT),--team-account)
apps-auth-configs: ## make apps-auth-configs [APP=] AS=admin: the team's app credentials (auth configs)
	@$(OPS_CLI) apps $(OPS_AS) auth-configs $(if $(APP),--app '$(APP)')

##@ Tools (ops tools)

tools-list: ## make tools-list AS=builder [APP=] [SEARCH=]: tool modules, or an app's tools
	@$(OPS_CLI) tools $(OPS_AS) list $(if $(APP),--app '$(APP)') $(if $(SEARCH),--search '$(SEARCH)')
tools-show: ## make tools-show ID=mod_… AS=builder: one tool module
	$(call need,ID,ID=mod_…)
	@$(OPS_CLI) tools $(OPS_AS) show $(ID)
tools-run: ## make tools-run APP=… TOOL=… INPUT='{"number": 1}' [REAL=1] AS=builder: run a tool, Mock unless REAL=1
	$(call need,APP,APP=plugin:acme.ticketdesk)
	$(call need,TOOL,TOOL=ticketdesk_get_ticket)
	@$(OPS_CLI) tools $(OPS_AS) run '$(APP)' $(TOOL) $(if $(INPUT),--input '$(INPUT)') $(if $(REAL),--real)
# The meeting flows' records in the team's Salesforce org (scripts/demo-org/okafor.json), each name marked with
# DEMO_ORG_PREFIX. Writes run as AS through the gateway as live calls, so the team must have added
# Salesforce's save_records (seed) and delete_record (remove) tools.
DEMO_ORG_PREFIX ?= [Demo]$(empty) $(empty)
DEMO_ORG_DATA = $(ROOT)/scripts/demo-org/okafor.json
DEMO_ORG_RUN = $(OPS_CLI) tools --as '$(AS)' --json run plugin:opsai.salesforce
DEMO_ORG_FILL = jq --arg prefix '$(DEMO_ORG_PREFIX)' --arg today "$$(date +%F)" \
	--arg ago17 "$$(date -v-17d +%F 2>/dev/null || date -d '-17 days' +%F)" \
	--arg in60 "$$(date -v+60d +%F 2>/dev/null || date -d '+60 days' +%F)" \
	'walk(if type == "string" then gsub("{prefix}"; $$prefix) | gsub("{today}"; $$today) | gsub("{ago17}"; $$ago17) | gsub("{in60}"; $$in60) else . end)' $(DEMO_ORG_DATA)
# The marked account's id, or nothing.
DEMO_ORG_FIND = $(DEMO_ORG_FILL) | jq --arg sq "'" '{q: ("SELECT Id FROM Account WHERE Name = " + $$sq + .account + $$sq)}' \
	| $(DEMO_ORG_RUN) salesforce_query --input - --real \
	| jq -rn 'try input catch error("the Salesforce query gave no answer") | if (.output.records | type) == "array" then (.output.records[0].Id // "") else error("the Salesforce query failed") end'
demo-org-seed: ## make demo-org-seed AS=james: the meeting flows' records in the team's Salesforce org (an account, its contact, an open opportunity, two Tasks, a Case), names marked [Demo]; skips them when the account is there
	$(call need,AS,AS=james)
	@set -e; found=$$($(DEMO_ORG_FIND)); \
	if [ -n "$$found" ]; then echo "FOUND  the demo account is already in the org ($$found); nothing made"; exit 0; fi; \
	saved=$$($(DEMO_ORG_FILL) | jq '{records: .records}' | $(DEMO_ORG_RUN) salesforce_save_records --input - --real --environment live); \
	ids=$$(echo "$$saved" | jq -c '.output.saved // empty'); \
	if [ -z "$$ids" ]; then echo "FAIL   nothing was saved: $$(echo "$$saved" | jq -c '{decision, denyMessage, output}')"; exit 1; fi; \
	acct=$$(echo "$$ids" | jq -r '.[0].id'); grace=$$(echo "$$ids" | jq -r '.[1].id'); \
	case=$$($(DEMO_ORG_FILL) | jq --arg a "$$acct" --arg g "$$grace" '.case | .fields.AccountId = $$a | .fields.ContactId = $$g | {records: [.]}' \
		| $(DEMO_ORG_RUN) salesforce_save_records --input - --real --environment live | jq -c '.output.saved // .output'); \
	echo "MADE   account $$acct, contact $$grace, an opportunity and two Tasks; case $$case"
demo-org-remove: ## make demo-org-remove AS=james: deletes the [Demo] account; Salesforce deletes its contact, opportunity, Tasks and Case with it
	$(call need,AS,AS=james)
	@set -e; found=$$($(DEMO_ORG_FIND)); \
	if [ -z "$$found" ]; then echo "GONE   no demo account in the org"; exit 0; fi; \
	jq -n --arg id "$$found" '{object: "Account", id: $$id}' | $(DEMO_ORG_RUN) salesforce_delete_record --input - --real --environment live \
		| jq -c '{decision, status, output}'; \
	again=$$($(DEMO_ORG_FIND)); [ -z "$$again" ] && echo "REMOVED the demo account $$found and its records" || { echo "FAIL   $$again is still there"; exit 1; }
tools-calls: ## make tools-calls AS=admin [TOOL=] [THREAD=] [LIMIT=20]: the tool-call log
	@$(OPS_CLI) tools $(OPS_AS) calls $(if $(TOOL),--tool $(TOOL)) $(if $(THREAD),--thread $(THREAD)) $(if $(LIMIT),--limit $(LIMIT))
tools-call: ## make tools-call ID=gwc_… AS=admin: one logged tool call
	$(call need,ID,ID=gwc_…)
	@$(OPS_CLI) tools $(OPS_AS) call $(ID)

##@ Runs and Human Tasks (ops runs, ops tasks)

runs-list: ## make runs-list AS=builder [WORKFLOW=]: workflow runs, newest first
	@$(OPS_CLI) runs $(OPS_AS) list $(if $(WORKFLOW),--workflow $(WORKFLOW))
runs-start: ## make runs-start WORKFLOW=… INPUT='k=v' [LIVE=1] [WAIT=1] AS=builder: start a run (a test run unless LIVE=1)
	$(call need,WORKFLOW,WORKFLOW=customer_summary)
	@$(OPS_CLI) runs $(OPS_AS) start $(WORKFLOW) $(if $(INPUT),--input '$(INPUT)') $(if $(LIVE),--live) $(if $(WAIT),--wait)
runs-show: ## make runs-show RUN=wfrun_… AS=builder: a run's status
	$(call need,RUN,RUN=wfrun_…)
	@$(OPS_CLI) runs $(OPS_AS) show $(RUN)
runs-events: ## make runs-events RUN=wfrun_… AS=builder: a run's events as they happen
	$(call need,RUN,RUN=wfrun_…)
	@$(OPS_CLI) runs $(OPS_AS) events $(RUN)
runs-cancel: ## make runs-cancel RUN=wfrun_… AS=builder: cancel a run
	$(call need,RUN,RUN=wfrun_…)
	@$(OPS_CLI) runs $(OPS_AS) cancel $(RUN)
runs-retry: ## make runs-retry RUN=wfrun_… AS=builder: queue a Stuck run again from its last step
	$(call need,RUN,RUN=wfrun_…)
	@$(OPS_CLI) runs $(OPS_AS) retry $(RUN)
tasks-list: ## make tasks-list AS=approver [VIEW=] [SEARCH=]: the Human Tasks queue
	@$(OPS_CLI) tasks $(OPS_AS) list $(if $(VIEW),--view $(VIEW)) $(if $(SEARCH),--search '$(SEARCH)')
tasks-show: ## make tasks-show TASK=… AS=approver: one Human Task
	$(call need,TASK,TASK=wfrun_…:task:1)
	@$(OPS_CLI) tasks $(OPS_AS) show '$(TASK)'
tasks-decide: ## make tasks-decide TASK=… DECISION=approve [REASON=] [FIELDS='k=v'] AS=approver: decide a Human Task
	$(call need,TASK,TASK=wfrun_…:task:1)
	$(call need,DECISION,DECISION=approve)
	@$(OPS_CLI) tasks $(OPS_AS) decide '$(TASK)' $(DECISION) $(if $(REASON),--reason '$(REASON)') $(if $(FIELDS),--fields '$(FIELDS)')

##@ Cases, files and documents (ops cases, ops files, ops documents)

cases-list: ## make cases-list AS=james [SEARCH=]: cases
	@$(OPS_CLI) cases $(OPS_AS) list $(if $(SEARCH),--search '$(SEARCH)')
cases-show: ## make cases-show CASE=case_… AS=james: one case
	$(call need,CASE,CASE=case_…)
	@$(OPS_CLI) cases $(OPS_AS) show $(CASE)
cases-note: ## make cases-note CASE=case_… TEXT='…' AS=james: add a note to a case
	$(call need,CASE,CASE=case_…)
	$(call need,TEXT,TEXT='Called the customer')
	@$(OPS_CLI) cases $(OPS_AS) note $(CASE) '$(TEXT)'
files-list: ## make files-list AS=james [SEARCH=] [PURPOSE=]: files
	@$(OPS_CLI) files $(OPS_AS) list $(if $(SEARCH),--search '$(SEARCH)') $(if $(PURPOSE),--purpose $(PURPOSE))
files-show: ## make files-show ID=fil_… AS=james: one file
	$(call need,ID,ID=fil_…)
	@$(OPS_CLI) files $(OPS_AS) show $(ID)
files-upload: ## make files-upload FILE=path PURPOSE=case_attachment AS=james: upload a file
	$(call need,FILE,FILE=notice.pdf)
	$(call need,PURPOSE,PURPOSE=case_attachment)
	@$(OPS_CLI) files $(OPS_AS) upload '$(FILE)' --purpose $(PURPOSE)
documents-types: ## make documents-types AS=builder: the document types
	@$(OPS_CLI) documents $(OPS_AS) types
documents-type: ## make documents-type ID=… AS=builder: one document type
	$(call need,ID,ID=dt_…)
	@$(OPS_CLI) documents $(OPS_AS) type $(ID)
documents-extractions: ## make documents-extractions ID=fil_… AS=builder: what was read from a file
	$(call need,ID,ID=fil_…)
	@$(OPS_CLI) documents $(OPS_AS) extractions --file $(ID)

##@ People, roles and models (ops people, ops models)

people-list: ## make people-list AS=admin: the team's members
	@$(OPS_CLI) people $(OPS_AS) list
people-invite: ## make people-invite EMAILS='a@x b@x' ROLE=viewer [SEND=1] AS=admin: print the invite; SEND=1 sends it
	$(call need,EMAILS,EMAILS=new.person@example.com)
	$(call need,ROLE,ROLE=viewer)
	@$(OPS_CLI) people $(OPS_AS) invite $(EMAILS) --role $(ROLE) $(if $(SEND),--send)
people-roles: ## make people-roles AS=admin: the roles and how many hold each
	@$(OPS_CLI) people $(OPS_AS) roles
people-me: ## make people-me AS=james: who the sign-in is, and their teams
	@$(OPS_CLI) people $(OPS_AS) me
models-aliases: ## make models-aliases AS=builder: the chat aliases an agent may name, with prices
	@$(OPS_CLI) models $(OPS_AS) aliases
models-providers: ## make models-providers AS=admin: the model provider connections (account admins)
	@$(OPS_CLI) models $(OPS_AS) providers
models-keys: ## make models-keys AS=admin: the provider keys by name (account admins)
	@$(OPS_CLI) models $(OPS_AS) keys
models-test: ## make models-test AGENT='Ops Assistant' CONFIRM=1 AS=builder: one test turn on an agent's model (costs money)
	$(call need,AGENT,AGENT='Ops Assistant')
	@$(OPS_CLI) models $(OPS_AS) test '$(AGENT)' $(if $(SAY),-m '$(SAY)') $(if $(CONFIRM),--confirm)

##@ Memories and test data (ops memories, ops test-data)

memories-list: ## make memories-list AS=james [AGENT=]: what the agents remember about this person
	@$(OPS_CLI) memories $(OPS_AS) list $(if $(AGENT),--agent '$(AGENT)')
memories-forget: ## make memories-forget ID=mem_… AS=james: forget one memory
	$(call need,ID,ID=mem_…)
	@$(OPS_CLI) memories $(OPS_AS) forget $(ID)
memories-forget-agent: ## make memories-forget-agent AGENT='Ops Assistant' AS=james: forget everything one agent remembers
	$(call need,AGENT,AGENT='Ops Assistant')
	@$(OPS_CLI) memories $(OPS_AS) forget-agent '$(AGENT)'
memories-export: ## make memories-export AS=james: every memory, as the export downloads it
	@$(OPS_CLI) memories $(OPS_AS) export
test-data-clean: ## make test-data-clean [AS=] [SINCE=2026-11-07] [CONFIRM=1]: list what test runs made ([test] prefix), for AS= or every seeded person; CONFIRM=1 removes it
	@$(OPS_CLI) test-data clean $(if $(filter command line environment,$(origin AS)),--people '$(AS)') \
		$(if $(SINCE),--since $(SINCE)) $(if $(CONFIRM),--confirm) $(if $(JSON),--json)
