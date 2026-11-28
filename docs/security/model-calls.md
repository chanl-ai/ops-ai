# Model calls

Status: current.

A risk team asks three things about any AI system. Which model endpoint sees customer data, under whose key, and what stops a runaway agent from spending without limit? In Ops AI every model call passes through one AI gateway inside your installation. That covers a chat turn, a workflow AI step and a document read, in every shipped layout: Docker Compose, Kubernetes and hosted. No agent, workflow or team ever holds the provider's key.

This page shows you how to connect the one endpoint your bank has approved, and what the gateway checks before any call leaves.

## Connect the approved endpoint

A Security admin connects the endpoint, and the workspace owner decides which model each alias points at.

<!-- site: steps -->
1. Open **Settings › Models › Connections** and connect a provider. Pick it from the list, then give its endpoint and key. After you save, the key is never shown again and no team can read it.
2. Open **Settings › Models › Aliases**. As the workspace owner, point an alias such as `default` at one of the provider's models, and record the highest data level that model may receive: public, internal, confidential or restricted.
3. Open an agent and press **Test**. The answer comes from your endpoint.
4. Open **Settings › Usage and cost** to see the tokens and cost. The models service keeps a call log with one row per call: the key, the model, tokens, cost, time taken and outcome. It holds no prompt or answer text.

Any endpoint that speaks the OpenAI chat completions API can serve: OpenAI, Anthropic and Google Gemini through their OpenAI-compatible APIs, Azure OpenAI, Amazon Bedrock, a private deployment, or your bank's own gateway.

## What success looks like

A test turn answers from the endpoint you chose, and the usage page shows its cost. A call that the gateway refuses is logged the same way, with the reason, so you can see why a call stopped, for example because the key had spent its budget or the model was not cleared for the data.

## What skipping the gateway would cost

If each agent held its own provider key, you could not tell which agent spent the money, a leaked key would mean finding every place that held it, and a confidential document could reach a model nobody had cleared for it. Routing every call through one gateway gives you one place to set budgets, rotate keys and read the log.

## What the gateway checks

<!-- site: sequence caption="A model call from an agent or workflow to your endpoint, and the checks in between" -->
1. **Agent or workflow → AI gateway**: Asks for a model by alias, with its own model key
   - The gateway checks that the key is known, not expired and not revoked, that it is within its budget and its calls-per-minute rate, and which model the alias points at.
2. **AI gateway → Your model endpoint**: Forwards the request with the provider key
   - Before this, the gateway checks that the alias is cleared for the data's level and for images. A refusal is logged and nothing leaves.
3. **Your model endpoint → AI gateway**: Answers
4. **AI gateway → Agent or workflow**: Returns the answer
   - The call is recorded with its key, model, tokens, cost, time taken and outcome, and no text.

## How keys and aliases work

- Agents and workflows name an alias such as `default` and not a provider's model id. Moving an alias to another model is a new version of the alias, and no agent changes.
- Each caller has its own model key: for a service purpose, an agent, a workflow or a person. Ops AI stores only a hash of the key. When you rotate a key, the old secret keeps working for 15 minutes so callers can pick up the new one.
- Provider keys are stored sealed, and they belong to one organisation. Outside development the gateway refuses provider keys from its environment, so a key exists only where an admin saved it.
- A model key can carry a budget, a limit on calls per minute, an expiry date and a daily spending cap that resets at midnight UTC.

## Settings

| Control | What it does | Default | Who changes it |
|---|---|---|---|
| Provider connections and keys | Where models are called and the key each signs in with | None until an admin adds one | A Security admin, in Settings › Models › Connections |
| Alias versions and clearance | The highest data level the model may receive, and whether it may receive images and files | Set on each version | The workspace owner, in Settings › Models › Aliases |
| Budget and rate per model key | A spending cap in money, and calls per minute. The call that would pass the cap is refused | Rate: 600 calls a minute. Budget: set when the key is issued | Whoever operates the installation, through the models service |
| Budget per organisation on a shared key | An organisation's share of a key's budget | Not set | Whoever operates the installation |
| Budget per conversation | Caps on model calls and cost for each chat. A spent budget pauses the chat until a person continues or ends it | 200 calls and 5.00 in the price table's currency, when the agent sets none. Never unlimited | A builder, on the agent |
| Model calls per turn | How many model calls one answer may make | 50 | A builder, on the agent |
| AI steps in workflows | Whether a team's workflows may call a model at all | Off | A builder or admin of the team, in Govern › Policies |

## What is not built yet

- Every call is treated as internal data today, so an alias must be cleared for internal data to serve any call. Marking each call with the level of the data it carries is planned.
- Model aliases belong to the installation, so every team on it shares them. Provider keys, model keys and the call log belong to one organisation each.
- Failover between providers and a budget per team are planned.
- The release includes a test model that answers from fixed rules and calls no provider. It is for trying the platform and for automated checks, and you should not use it in production.

## Next

<!-- site: cards -->
- **[Data handling and masking](data-handling-and-masking.md)**: What people see masked while the model sees real values.
- **[Egress and connections](egress-and-connections.md)**: The other calls that leave the install.
- **[Models in depth](../guide/models.md)**: Aliases, keys and the test model.
