# Build your first tool

Status: current for REST tools. Code tools, a function an agent calls, are not built in the console yet.

**Build a REST Tool on your own API, run it safely in Mock, then for real, and give it to an agent.**

## Your agent cannot reach your API yet

A Tool lets an agent act on one of your Apps. Without one, the agent can describe what it would do and cannot do it, and
the team is tempted to paste API keys into prompts to make it work.

This page takes you from nothing to a REST Tool an agent uses, in the order an API client works: an App that signs in, a
request, a run in Mock, a run for real, then the agent. The example is a payments API that takes a new customer as a
form body behind a Bearer key. [Apps](apps.md) explains the Apps menu these steps start from.

## The plan

<!-- site: steps -->
1. **Add the App** that holds the key.
2. **Write the request** as a Tool operation.
3. **Run it in Mock**, then **for real**.
4. **Give it to an agent.**

## Before you start

| You need | Why |
|---|---|
| The Builder role in your team | Builders make and edit Tools |
| An Admin in your team | Admins add Apps, whose Account holds the key |
| The App's host on the egress list | Security lists every host a Tool may call |

## Try it

<!-- site: steps -->
1. **Add the App.** An Admin opens **Data Gateway › Apps**, presses **Add custom app**, enters the App's address and
   its Bearer key, and tests it. The key never shows again; the test answers from the App.
2. **Make the Tool.** Open **Data Gateway › Tools**, press **New tool**, name it and pick the App, then add an operation
   with a name, read or write, and the method. The Tool's page shows the App's address in front of the request.
3. **Write the request.** Write the path, for example `/v1/customers`, and the body: JSON, Form or Raw. For the
   example, pick Form with one field, `email` = `{email}`. Each `{name}` and `{{name}}` becomes an input.
4. **Run it in Mock.** Type a value for each input and press **Run** in **Mock**. The Tool answers from its mock
   answers, and nothing leaves the gateway.
5. **Save and publish.** Press **Save**, then publish; Security reviews the first version. A save that breaks a rule
   lists every problem at once.
6. **Run it for real.** Switch to **Real** and press **Run**. You see the App's answer, badged Real, and Request sent:
   the address with its values, the key hidden, the body as encoded.
7. **Give it to an agent.** Grant the Tool to an agent in a workflow, and publish the workflow. The agent calls the
   Tool; a write waits when approvals are on for the team, the App or the Tool.

## What success looks like

The Real run shows the App's answer badged Real, and **Request sent** with the key hidden. An agent given the Tool
calls it, and a write waits when approvals are on for the team, the App or the Tool, or when it arrives over MCP.

## What skipping it costs

Without a Tool on an App, each place that needs the key holds its own copy, and a rotated key is changed in each one.
A request never run in Mock makes its first test a write to live data.

## Mock and Real

Mock changes nothing; Real sends the request.

<!-- site: compare caption="The two ways to run a Tool, and what each one changes" -->
- **Mock**: Answers from the Tool's mock answers
  - **Sends**: Nothing
  - **A write**: Changes nothing
  - **Needs**: The Tool's mock answers
  - **Who**: People who may run tools in the Tool's team, Builders and Admins; an API key cannot
- **Real**: Sends the request, signed in by the App's Account
  - **Sends**: The request, with its values filled in
  - **A write**: Uses the App's test account when it has one; on a live account it asks you first by default
  - **Needs**: A published Tool; an Account when the App needs a sign-in
  - **Who**: People in the Tool's team; an API key cannot

Keys belong on the App. A key typed into a Tool's Authorization header is refused when you save, so one key serves every
Tool that calls the App and is changed in one place.

## Not built yet

- Code tools: a function that shapes what a REST Tool returns.
- API keys that build Tools from a script.

## Next

<!-- site: cards -->
- [Connect an app and use it in an agent](use-cases/connect-an-app.md): give the Tool to an agent and use it in chat.
- [Hold a write for approval](use-cases/approve-a-write.md): make the Tool's writes wait for a person.
- [Sign in with a key or password](integrations/sign-in-keys.md): the kinds of key an App can hold.
