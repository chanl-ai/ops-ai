# Build your first tool

Status: current for REST tools. Code tools, a function an agent calls, are not built in the console yet.

A Tool lets an agent act on one of your Apps. This page takes you from nothing to a REST Tool an agent uses, in the
order an API client works: an App that signs in, a request, a run in Mock, a run for real, then the agent. The example
is a payments API that takes a new customer as a form body behind a Bearer key. [Apps](apps.md) explains the Apps menu
these steps start from.

## Before you start

| You need | Why |
|---|---|
| The Builder role in your team | Builders make and edit Tools |
| An Admin in your team | Admins add Apps, whose Account holds the key |
| The App's host on the egress list | Security lists every host a Tool may call |

## Steps

| # | Do | You see |
|---|---|---|
| 1 | An Admin opens **Apps**, presses **Add custom app**, enters the App's address and its Bearer key, and tests it | The key never shows again; the test answers from the App |
| 2 | Open **Apps › Tools**, press **New tool**, name it and pick the App, then add an operation with a name, read or write, and the method | The Tool's page, with the App's address in front of the request |
| 3 | Write the path, with `{email}` for a value the agent supplies, and the body: JSON, Form or Raw | Each `{name}` and `{{name}}` becomes an input |
| 4 | Type a value for each input and press **Run** in **Mock** | The Tool's mock answer; nothing leaves the gateway |
| 5 | Press **Save**, then publish; Security reviews the first version | A save that breaks a rule lists every problem at once |
| 6 | Switch to **Real** and press **Run** | The App's answer, badged Real, and Request sent: the address with its values, the key hidden, the body as encoded |
| 7 | Grant the Tool to an agent in a workflow, and publish the workflow | The agent calls the Tool; a write waits only when your team turned approvals on |

## Mock and Real

| | Mock | Real |
|---|---|---|
| Sends | Nothing; answers from the Tool's mock answers | The request, signed in by the App's Account |
| A write | Changes nothing | Changes data in the App, and is logged under your name |
| Needs | Nothing | A published Tool; an Account when the App needs a sign-in |
| Who | Anyone who can see the Tool, viewers included | People in the Tool's team; an API key cannot |

Keys belong on the App. A key typed into a Tool's Authorization header is refused when you save, so one key serves every
Tool that calls the App and is changed in one place.

## Not built yet

- Code tools: a function that shapes what a REST Tool returns.
- API keys that build Tools from a script.
- `ops login`: the SDK reads its address and key from arguments, `OPS_*` variables or a profile file you write.

Proof: uc-611 runs these steps against a payments stand-in, in a browser and through the API.
