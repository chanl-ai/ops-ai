# Egress and connections

Status: current.

An agent that can reach your core banking system could, in principle, be talked into reaching somewhere else with the same customer data. Your security team needs to know that cannot happen, and that the agent never holds the passwords it uses.

In Ops AI, every call to an outside system goes through one data gateway. The gateway holds the credentials, checks the destination against a list you control and records the call. Agents and workflows hold no credentials and open no connections of their own.

## Allow the first host

A Security admin allows one host, then a builder connects an app that uses it.

<!-- site: steps -->
1. As a Security admin, add the host your tools need to reach. In the console, open **Settings › Security › Egress** and choose **Add host**. From the command line:

   ```bash
   opsai egress allow-host api.core-banking.example.com
   opsai egress list
   ```

2. If the host is on a private network, choose **Add range** and enter the network in CIDR form, for example `10.20.0.0/16`. Public hosts need no range.
3. As a builder, open the app in **Data › Apps**, turn it on and run one of its tools.
4. Open **Govern › Activity** and find the call. It shows the tool, who it ran for and what came back.

When a builder connects an app that names an address nobody has allowed, the default is to hold the request and create a human task for the Security team. Approving the task adds the host to the list and the builder's screen retries what it was doing.

## What success looks like

A tool call to the listed host succeeds and appears in the activity record. A call to any other host fails, and the message names the host that was refused, so a builder knows what to ask Security for. The agent sees the refusal as a tool error and can explain it to the person.

## What skipping the list costs

With the "Any public address" choice, tools may call any public host without anyone listing it. The gateway still blocks private, loopback, link-local and cloud metadata addresses, but a tool that a builder points at a host outside your control can send data there. Teams in regulated settings usually keep the default, where a Security admin approves each new host.

## How a call leaves

<!-- site: sequence caption="A tool call from an agent to one of your systems, and what the gateway does on the way" -->
1. **Agent → Data gateway**: Calls a tool with some input
   - The gateway checks the tool exists, the input matches its schema, and the rate and amount limits hold. A change that needs approval waits here, as [Access, approvals and audit](access-approvals-and-audit.md) describes.
2. **Data gateway → Credential store**: Asks for the connection's credential
3. **Credential store → Data gateway**: Returns it
4. **Data gateway → Your system**: Calls it over HTTPS
   - The host must be on the allow-list. Every address the host resolves to is checked, and the call goes to the checked address, so a DNS answer cannot redirect it.
5. **Your system → Data gateway**: Answers
6. **Data gateway → Agent**: Returns the answer
   - Credentials are scrubbed from the answer, and the call is recorded with its outcome.

A refusal lists every condition that failed.

## The rules the gateway follows

- Only HTTPS is called. Redirects are not followed, and cookies are not kept.
- Private address ranges are reached only when a Security admin lists them. Loopback, link-local, multicast and cloud metadata addresses can never be listed and are never reached.
- When you provide your internal certificate authority, the gateway trusts it for outbound calls.
- A plugin can declare the hosts it needs for its own calls, and those calls do not need listing.
- A connection can sign in with an API key, a username and password, a bearer token, OAuth client credentials, OAuth authorization code with PKCE, or a signed service-account token. Either OAuth kind can use a signed client assertion in place of a secret, and any kind can add a client certificate for mutual TLS. Ops AI stores tokens encrypted and renews them.
- A person can connect an app with their own account. Tools they run, and agents acting for them, then use that account.
- A code tool runs in a sandbox with a memory limit, a time limit, no network, no files and no secrets. It reaches other systems only by calling a tool back through the gateway, and those calls are checked as the original caller's.

## Settings

| Setting | What it does | Default | Who changes it |
|---|---|---|---|
| New app addresses | What happens when an app or tool names an address nobody has allowed: ask Security, let builders allow it in their own name, allow any public address, or refuse anything not listed | Ask Security | A Security admin, in Govern › Policies |
| Allow-list | The hosts and private ranges tools may reach | Empty | A Security admin, in Settings › Security › Egress, or with `opsai egress` |
| Only Security adds secrets | Builders may not add their team's own secrets | Off: builders add and use their team's secrets | A Security admin, in Govern › Policies |
| Credentials | Entered once in the console, sealed with AES-256-GCM, never returned by any API, scrubbed from answers and logs, and limited to the teams they are shared with | Not applicable | A Security admin for shared credentials, or a builder for a team's own, in Data › Secrets |

## What is not built yet

- Writing a code tool in the console is planned. A code tool runs today in the sandbox described above.
- Keeping credential values in your own key vault is planned.

## Next

<!-- site: cards -->
- **[Access, approvals and audit](access-approvals-and-audit.md)**: Which writes wait for a person before the gateway sends them.
- **[Model calls](model-calls.md)**: The other kind of call that leaves the install.
- **[Tools and apps](../guide/apps.md)**: Connecting an app and choosing its accounts.
