# Build your first tool

Status: current.

This guide shows you how to build a REST tool on your own API, run it safely in Mock and then for real, and give it to
an agent. It covers REST tools only. Code tools, which are functions an agent calls, can't be built in the console yet.

## Your agent cannot reach your API yet

A tool lets an agent act on one of your apps. Without one, the agent can describe what it would do but can't actually
do it. That gap tempts your team to paste API keys into prompts to make it work.

This page takes you from nothing to a REST tool an agent uses, in the order an API client works. You add an app that
signs in, write a request, run it in Mock, run it for real, and then hand it to the agent. The example is a payments
API that takes a new customer as a form body and expects a Bearer key. [Apps](apps.md) explains the Apps menu that
these steps start from.

## The plan

<!-- site: steps -->
1. **Add the app** that holds the key.
2. **Write the request** as a tool operation.
3. **Run it in Mock**, then **for real**.
4. **Give it to an agent.**

## Before you start

| You need | Why |
|---|---|
| The Builder role in your team | Builders make and edit tools |
| An Admin in your team | Admins add apps, and the app's account holds the key |
| The app's host on the egress list | Security keeps a list of every host a tool may call |

## Try it

<!-- site: steps -->
1. **Add the app.** An Admin opens **Data Gateway › Apps**, presses **Add custom app**, enters the app's address and
   its Bearer key, and tests the connection. The key is never shown again, and the test result comes back from the app
   itself.
2. **Make the tool.** Open **Data Gateway › Tools** and press **New tool**. Give the tool a name and pick the app. Then
   add an operation with a name, choose whether it reads or writes, and pick the method. The tool's page shows the
   app's address in front of the request.
3. **Write the request.** Enter the path, for example `/v1/customers`, and choose a body type of JSON, Form or Raw. For
   the example, pick Form with one field, `email` = `{email}`. Each `{name}` and `{{name}}` you write becomes an input
   that you fill in when the tool runs.
4. **Run it in Mock.** Type a value for each input, then press **Run** in **Mock**. The tool replies with its mock
   answers, and nothing leaves the gateway.
5. **Save and publish.** Press **Save**, then publish. Security reviews the first version. If a save
   breaks a rule, you see every problem at once rather than one at a time.
6. **Run it for real.** Switch to **Real** and press **Run**. You see the app's answer with a Real badge, along with
   **Request sent**, which shows the address with your values filled in, the key hidden and the body as it was encoded.
7. **Give it to an agent.** Grant the tool to an agent in a workflow, then publish the workflow. The agent can now call
   the tool. If approvals are turned on for the team, the app or the tool, any action that changes data waits for
   someone to approve it.

## What success looks like

When the tool works, the Real run shows the app's answer with a Real badge, and **Request sent** shows the request with
the key hidden. An agent you give the tool to can call it. Any action that changes data waits for approval when
approvals are on for the team, the app or the tool, and also whenever the call arrives over MCP.

## What skipping it costs

If you don't put a tool on the app, every place that needs the key keeps its own copy. When the key is rotated, someone
has to change it in each of those places. And if you never run a request in Mock, its first test is a change to live
data.

## Mock and Real

Running in Mock changes nothing, while running in Real sends the request to the app.

<!-- site: compare caption="The two ways to run a tool, and what each one changes" -->
- **Mock**: Answers from the tool's mock answers
  - **Sends**: Nothing
  - **A write**: Changes nothing
  - **Needs**: The tool's mock answers
  - **Who**: People who may run tools in the tool's team, Builders and Admins. An API key can't run it
- **Real**: Sends the request, signed in with the app's account
  - **Sends**: The request, with its values filled in
  - **A write**: Uses the app's test account when it has one. On a live account it asks you first by default
  - **Needs**: A published tool, and an account when the app needs a sign-in
  - **Who**: People in the tool's team. An API key can't run it

Keep keys on the app. If you type a key into a tool's Authorization header, the save is refused. That way one key
serves every tool that calls the app, and when it changes you update it in one place.

## Not built yet

- Code tools: a function that shapes what a REST tool returns.
- API keys that build tools from a script.

## Next

<!-- site: cards -->
- [Connect an app and use it in an agent](use-cases/connect-an-app.md): give the tool to an agent and use it in chat.
- [Hold a write for approval](use-cases/approve-a-write.md): make the tool's writes wait for a person.
- [Sign in with a key or password](integrations/sign-in-keys.md): the kinds of key an app can hold.
