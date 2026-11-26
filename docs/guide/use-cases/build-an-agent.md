# Build an agent

Status: current. The samples follow the Python and TypeScript SDKs, the command line and the HTTP API as they ship.

A lending servicing team gets the same questions every day: what a payoff statement includes, how long a hardship
review takes, which documents a borrower must send. This guide builds an agent that answers them from the team's own
policy, tries it as a draft, gives it the team's knowledge and a tool, and publishes it so the team can chat with it.
The same steps fit any team's agent.

## Before you start

| You need | Where to get it |
|---|---|
| Ops AI running and you signed in | [Quickstart](../quickstart.md), about ten minutes on one machine |
| The Builder role on your team | A team admin grants it ([Teams and access](../teams-and-access.md)) |
| A second person with the Reviewer role | They approve the first publish; see step 5 |

The samples use a signed-in profile: `opsai login` once, then the SDKs and the command line read it. Over HTTP, send
an API key from the console's Settings › API keys in `X-Api-Key` and your team in `X-Team-Id`
([HTTP API](../../reference/http-api.md)).

## Steps

<!-- site: steps -->
1. **Write the agent.** An agent needs a name and a role; its instructions say what it answers and how. Start in the
   console under **Build › Agents**, or from code:

   ```python tab="Python"
   from ops_ai import OpsAI

   ops = OpsAI()
   agent = ops.agents.apply({
       "name": "Servicing helper",
       "role": "Answer servicing questions from borrowers",
       "instructions": "Answer in two sentences. A payoff statement is valid for 10 days.",
   })
   print(agent["id"])
   ```

   ```ts tab="TypeScript"
   import { OpsAI } from '@chanl-ai/ops-ai';

   const ops = new OpsAI();
   // apply creates a new agent each time in TypeScript, so call it once and keep the id.
   const agent = await ops.agents.apply({
     name: 'Servicing helper',
     role: 'Answer servicing questions from borrowers',
     instructions: 'Answer in two sentences. A payoff statement is valid for 10 days.',
   });
   console.log(agent.id);
   ```

   ```bash tab="CLI"
   cat > servicing-helper.yaml <<'EOF'
   name: Servicing helper
   role: Answer servicing questions from borrowers
   instructions: Answer in two sentences. A payoff statement is valid for 10 days.
   EOF
   opsai agents validate servicing-helper.yaml
   AGENT=$(opsai agents --json apply servicing-helper.yaml | jq -r .id)
   ```

   ```bash tab="HTTP"
   curl -X POST "https://ops.example.com/api/agents/v1/agents" \
     -H "X-Api-Key: $OPS_API_KEY" -H "X-Team-Id: $OPS_TEAM" -H "Content-Type: application/json" \
     -d '{"name": "Servicing helper", "role": "Answer servicing questions from borrowers",
          "instructions": "Answer in two sentences. A payoff statement is valid for 10 days."}'
   ```

   In Python and the command line, `apply` updates the draft of an agent that already has this name, so the file can
   live in version control and be applied again after each edit.

2. **Try the draft.** A test turn runs the draft as the console's **Test** panel does. Nobody else sees it.

   ```python tab="Python"
   print(ops.agents.test(agent["id"], "How long is a payoff statement valid?"))
   ```

   ```ts tab="TypeScript"
   console.log(await ops.agents.test(agent.id, 'How long is a payoff statement valid?'));
   ```

   ```bash tab="CLI"
   opsai agents test "$AGENT" --message "How long is a payoff statement valid?"
   ```

   ```bash tab="HTTP"
   curl -X POST "https://ops.example.com/api/agents/v1/agents/$AGENT/test" \
     -H "X-Api-Key: $OPS_API_KEY" -H "X-Team-Id: $OPS_TEAM" -H "Content-Type: application/json" \
     -d '{"message": "How long is a payoff statement valid?"}'
   ```

   Expected: with a real model, an answer that says 10 days, from the instructions alone. The built-in test model
   answers with a sentence naming the agent and your message, which shows the draft runs ([Models](../models.md#the-test-model)).

3. **Give it the team's knowledge.** Put the servicing manual in a knowledge base first
   ([Answer from your documents](answer-from-documents.md)), then add that knowledge base to the agent. Its answers
   then cite the page and section they came from.

   ```python tab="Python"
   ops.agents.add_reference(agent["id"], "knowledge", "<knowledge base id>")
   ```

   ```ts tab="TypeScript"
   await ops.agents.addReference(agent.id, 'knowledge', '<knowledge base id>');
   ```

   ```bash tab="CLI"
   opsai kb bases                                   # the team's knowledge bases and their ids
   opsai agents add-reference "$AGENT" knowledge <knowledge base id>
   ```

4. **Give it a tool.** Tools are operations on your systems, such as looking up a loan. List what the agent may be
   granted and add the ones it needs. Each tool keeps its own approval setting, so a write can still wait for a person
   ([Hold a write for approval](approve-a-write.md)).

   ```python tab="Python"
   for option in ops.agents.tool_options(search="loan"):
       print(option["id"], option.get("name"))
   ops.agents.grant_tools(agent["id"], ["<tool id>"])
   ```

   ```ts tab="TypeScript"
   for (const option of await ops.agents.toolOptions('loan')) console.log(option.id, option.name);
   await ops.agents.grantTools(agent.id, ['<tool id>']);
   ```

   ```bash tab="CLI"
   opsai agents tool-options --search loan
   opsai agents grant-tools "$AGENT" <tool id>
   ```

   No tools yet? [Connect an app to an agent](connect-an-app.md) turns one on.

5. **Publish it.** People chat with the published version, so a change reaches them only after you publish. A first
   publish waits for a second person to review it ([how a version moves](#how-a-version-moves)).

   ```python tab="Python"
   request = ops.agents.publish(agent["id"], note="First version")
   print(request["status"])
   ```

   ```ts tab="TypeScript"
   const request = await ops.agents.publish(agent.id, 'First version');
   console.log(request.status);
   ```

   ```bash tab="CLI"
   opsai agents publish "$AGENT" --note "First version"
   ```

   ```bash tab="HTTP"
   # version is the draft's current version, from GET /v1/agents/{id}
   curl -X POST "https://ops.example.com/api/agents/v1/agents/$AGENT/publish-requests" \
     -H "X-Api-Key: $OPS_API_KEY" -H "X-Team-Id: $OPS_TEAM" -H "Content-Type: application/json" \
     -d '{"version": 1, "note": "First version"}'
   ```

6. **Chat with it.** Once the publish is approved, anyone on the team can pick the agent in the console's chat. From
   code, one message starts a conversation:

   ```python tab="Python"
   reply = ops.agents.chat(agent["id"], "What does a payoff statement include?")
   print(reply["reply"])
   ```

   ```ts tab="TypeScript"
   const reply = await ops.agents.chat(agent.id, 'What does a payoff statement include?');
   console.log(reply.reply);
   ```

   ```bash tab="CLI"
   opsai agents chat "$AGENT" --message "What does a payoff statement include?"
   ```

Expected, with a real model: an answer drawn from the servicing manual, with the page and section cited. If the agent called a tool, the
reply lists the call.

## Choices along the way

| Choice | Options | Default |
|---|---|---|
| Where you write it | The console, a file applied from the command line, or the SDKs | Any; all three save the same draft |
| Model | A model alias set by an account admin; changing what the alias points at changes the model without editing the agent | The team's default alias |
| Who reviews a publish | Every publish, a major change only, or none except security changes; set per team | A first publish and other major changes |
| Writes wait for a person | Per tool, App or team | Off until a team turns it on |

## How a version moves

Only a published version reaches the team. A first publish waits for a second person to review it; a later change to
the name or role publishes at once. A team admin can change this per team.

```mermaid caption="How an agent version moves from draft to published, and why an edit never changes a conversation under way"
flowchart TD
  A[Draft, in Test] -->|Publish| B[Second person reviews]
  B -->|Approved| C[Published version]
  C -->|Edit| A
```

A published version does not change. Editing makes a new draft, and a conversation already under way keeps the version
it started on.

## Limits

- `apply` in TypeScript creates a new agent each call; use `update` with the id to change a draft.
- Adding knowledge and granting tools over HTTP need the draft's version with each change; use an SDK or the command
  line for those steps.

## Next

<!-- site: cards -->
- [Connect an app to an agent](connect-an-app.md): Let the agent read and write a system such as Salesforce.
- [Hold a write for approval](approve-a-write.md): Make the agent's writes wait for a reviewer.
- [Agents](../agents.md): Every part of an agent, from skills to guardrails and budgets.
- [Agent examples](../examples/agents.md): Streaming runs, scoring with test cases and more, in each SDK.
