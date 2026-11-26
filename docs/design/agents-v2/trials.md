# Trials for agents version 2

Status: proposed design, written 2026-11-26. No trial has been run. Each result is written into this page when its trial
ends.

A trial is a short experiment that answers one question the specs could not settle from documentation. Each has a plan
someone can run in a day or two, one line that says what passing means, the build step that waits for it, and what we
do if it fails. Fifteen trials are listed in the order they should run. The first four gate release 1.4.0, the next six
gate 1.5.0 and the last five gate 1.6.0. Trial code is thrown away: it lives on a branch named for the trial and is not
merged.

## How a trial is run

| Rule | Detail |
|---|---|
| Where | A scratch branch and a scratch folder outside the product's packages. No product code changes |
| Model | The scripted model unless the trial says "real model"; real-model parts use a development key through the model gateway |
| Result | One paragraph under the trial on this page: the date, pass or fail, the numbers, and the versions of the libraries used |
| A fail | The fallback column is taken, and the spec that named the trial is updated in the same pull request |
| Library facts | Every fact a trial confirms replaces an "unverified" mark in the specs, with the version it was confirmed on |

## Order

| # | Trial | Gates | Release |
|---|---|---|---|
| 0 | Licences and status of every new dependency | Adding any dependency | all |
| 1 | A paused turn saved and resumed on another server | The Strands driver's pause design | 1.4.0 |
| 2 | Step-hold rules on Strands hooks | Porting the 13 kernel features | 1.4.0 |
| 3 | Event stream mapping, and six smaller checks | The chat stream, the scripted model, the builder | 1.4.0 |
| 4 | A swarm paused for days | Only the choice between runtime-driven and library-driven hand-overs | 1.4.0, not blocking |
| 5 | A Sprite's network allow-list and restore after sleep | The Sprites backend | 1.5.0 |
| 6 | The SSH sandbox driving a Sprite, and Strands' tools on our sandbox | The kernel's sandbox adapter | 1.5.0 |
| 7 | Adding a secret at the exit gate | The exit gate's inspect mode | 1.5.0 |
| 8 | Isolation level per install | The Docker and Kubernetes defaults | 1.5.0 |
| 9 | Start time and the warm pool | Pool sizes; whether WebAssembly stays for functions | 1.5.0 |
| 10 | Save, sleep and wake with 1 GB of files | The save design and its limits | 1.5.0 |
| 11 | A waiting run across an upgrade | Rebuild from the journal | 1.6.0 |
| 12 | A crash in the middle of a team, on both databases | Engine-driven hand-overs and cycles | 1.6.0 |
| 13 | An agent step paused for approval | The agent port's pause and resume | 1.6.0 |
| 14 | The engine on SQL Server under load | Removing the engine's lines from the portable baseline | 1.6.0 |

Trials 1, 2 and 3 can run in parallel after trial 0. Trials 5 to 10 can run in parallel. Trials 11 to 14 can run in
parallel; 13 needs trial 1's result.

## Trial 0: licences and status

Question: may we depend on each part, and is it maintained?

| Step | Action |
|---|---|
| 1 | For each part below, read the licence file in its repository at the version we would pin, and the licences of what it installs (`pip-licenses` or `license-checker` on a clean install) |
| 2 | Record the last release date, the release cadence over 12 months, and open security advisories |
| 3 | Record anything that is AGPL, SSPL, source-available or has a field-of-use limit |

| Part | Stated today | To confirm |
|---|---|---|
| Strands Agents Python SDK | Apache-2.0 on its repository page | The sandbox tools' package and licence; transitive licences |
| OpenHands agent server | The main repository states MIT; the agent server is in a separate SDK repository | That repository's licence. Not adopted in 1.5.0 either way |
| Anthropic sandbox-runtime | Apache-2.0; a beta research preview by its authors' description | Whether "research preview" carries any use limit |
| gVisor, Kata Containers | Open source; Kata states Apache-2.0 on its site | Both licences from their repositories |
| A YAML parser for the TypeScript SDK | Not chosen | Licence and size |
| A search provider adapter | Not chosen | The provider's terms for a self-installed product |
| The Kubernetes project's sandbox resource | Unverified | Status and licence; not adopted unless mature |
| Fly Sprites | A hosted service, not a dependency | Terms for running tenants' code; regions |

Pass: every part we would add is under Apache-2.0, MIT, BSD or a comparable permissive licence, with no AGPL anywhere
in its install tree, and has had a release in the last six months.

Fail: the part is not added. The specs name a fallback for each: our own loop driver stays possible behind the contract;
the sandbox needs none of the optional parts.

## Trial 1: a paused turn saved and resumed on another server

Question: can a Strands agent that paused for an approval be rebuilt in a fresh process from bytes we stored, and
continue?

| Step | Action |
|---|---|
| 1 | Process A: build an agent with one read tool and one write tool against the scripted model. A hook on the write tool raises an interrupt |
| 2 | Run a message that reads, then tries the write. Confirm stop reason `interrupt` and one pending interrupt |
| 3 | `take_snapshot(preset="session")`, `to_dict()`, serialise to bytes, write to a file. Exit process A |
| 4 | Process B, a fresh interpreter: build an agent from the same settings, `load_snapshot`, and resume with the interrupt response "approved" |
| 5 | Confirm the write tool runs once, the read tool does not run again, and the reply completes |
| 6 | Repeat with "rejected", with two tool calls pending in one step, and with the snapshot loaded 10 times in a row (size must not grow) |
| 7 | Measure the snapshot's size after 5, 20 and 60 messages |

Pass: steps 5 and 6 hold on the pinned version, and a 60-message snapshot is under 2 MB.

Gates: the pause persistence decision in the runtime contract (our checkpoint holds `LoopState`).

Fallback: if a pending interrupt is not restored, the kernel rebuilds the agent from our own transcript and re-raises
the interrupt itself (`LoopDriver.rebuild`), or uses a Strands session manager on a storage backend of ours. Both are
described in the runtime contract.

## Trial 2: step-hold rules on Strands hooks

Question: can our before-and-after rules run on Strands' hooks with the same effect they have today?

| Step | Action |
|---|---|
| 1, part a | Refuse a tool: a before-tool hook cancels a call; the model receives our refusal text as the tool result and continues |
| 2, part b | Replace a result: an after-tool hook swaps a result for a masked one; the next model request contains only the masked text |
| 3, part c | Guide and retry: after a model answer that fails a rule, make the model try again with a correction, at most twice, and count the model calls |
| 4, part d | Narrow the tools per call: offer 5 of 40 registered tools on one model request and a different 5 on the next |
| 5, part e | Stable-first prompt: confirm the system prompt and tool list bytes are identical across steps when only the tail changes, by comparing request bodies at the scripted gateway |
| 6, part f | Parallel reads: two read tools requested in one step run concurrently and both results return in order |
| 7 | Run all parts with streaming on |

Pass: parts a, b, c, e and f behave as described on the pinned version.

Gates: the port of the 13 kernel features onto `LoopSeams`.

Fallback: for a failing part, the seam is implemented by wrapping the tool or the model client ourselves instead of
using the hook. For part d, every granted tool is registered and tool search only ranks them; the runtime contract
already allows this.

## Trial 3: event stream mapping, and six smaller checks

Question: does the library's event stream carry everything our chat stream shows, in an order we can map?

| Step | Action |
|---|---|
| 1 | Run five scripted turns through `stream_async`: text only; one tool; two tools in one step; a typed answer; a turn cut by the steps limit |
| 2 | Record every event with its type and order. Fill the mapping table in the runtime contract with what was seen, and mark any of our events with no source |
| 3 | Confirm text arrives in pieces, a tool's start and end can be told apart, and the final result carries token counts including cached tokens |
| 4 | Cancel a turn mid-stream with the cancel signal and record what arrives |
| part a | Record the exact constructor arguments of the OpenAI-compatible provider for a base URL, extra headers and an injected HTTP client |
| part b | Replay: record a streamed model answer at a stub gateway, serve it again as a stream, and compare the loop's events |
| part c | Offloader: give the context offloader a storage object of ours and confirm a large tool result is stored there and referenced |
| part d | Real model, 20 requests: does the model call the mode tool with a useful reason, and does it stay direct for lookups? Count agreement with a reviewer's label |
| part e | Images: pass one image through the gateway to a model that accepts images |
| part f | Builder: draft the ten seeded descriptions on two model aliases; count drafts that validate and sections a reviewer would accept |

Pass: every frame the chat stream has today has a source event or a kernel-made one; replayed and live streams produce
the same events; part d agrees with the reviewer on at least 17 of 20.

Gates: the stream mapping, the scripted model seam, the replay design in the model gateway, the `mode_in` eval check
and the builder's model choice.

Fallback: a missing event is produced by the kernel from the seams. If replayed streams differ, replay returns the whole
answer as one piece and the chat shows it at once on a resumed turn. If part d fails, automatic mode ships with plan
and helpers triggered by rules (a write requested, or more than three tools named) instead of by the model's choice.

## Trial 4: a swarm paused for days

Question: can Strands' multi-agent swarm pause in the middle, be stored by us, and resume in another process?

| Step | Action |
|---|---|
| 1 | Build a three-agent swarm on the scripted model; the second agent's write tool raises an interrupt |
| 2 | Run until the pause; store whatever state the library offers; exit |
| 3 | In a fresh process, restore and resume with an approval; confirm the first agent does not run again and the third does |
| 4 | Confirm each agent's model calls went through our endpoint with its own budget header, and each tool call through our executor |

Pass: step 3 holds without a session manager that writes outside our database, and step 4 shows per-agent headers.

Gates: nothing in the build. The specs choose runtime-driven hand-overs, where each agent is its own turn. A pass makes
the library's swarm an option to revisit.

Fallback: none needed.

## Trial 5: a Sprite's network allow-list and restore after sleep

Question: can a Sprite be sealed to one host, and are its files there after it sleeps?

| Step | Action |
|---|---|
| 1 | Read the Sprites OpenAPI document; record the endpoints for create, exec, files, network policy, resources policy and delete |
| part a | Create a Sprite. Set a policy with one allow rule for a host we run. From inside: that host answers; three public hosts fail by name and by address; a DNS lookup of another host fails. Confirm the policy file is read-only inside |
| part b | Leave it idle until it is cold. Wake it. Read the policy back and repeat part a's checks. Confirm a file written before is present with the same hash and that a process started before is gone |
| part c | Try to cap a command at 2 GB of memory and one CPU: from inside with a control group as the default user, and from outside with the resources policy endpoint |
| part d | Measure: create to first command; cold wake to first command; our setup script for the data image. Try seeding a new Sprite from a checkpoint of a prepared one |
| 2 | Delete the Sprite and confirm it is gone from the list |

Pass: parts a and b hold; a cap from part c works by either route; create to first command with the image ready is
under 60 seconds and cold wake under 3 seconds.

Gates: the Sprites backend.

Fallback: if the allow-list cannot seal a Sprite, hosted tenants run on the Kubernetes backend in our own cluster and
Sprites is dropped. If memory cannot be capped, hosted sandboxes offer one size. If setup is slow, a pool of prepared
Sprites is kept per image.

## Trial 6: the SSH sandbox driving a Sprite, and Strands' tools on our sandbox

Question: is Strands' SSH sandbox a usable way to reach a Sprite, and do Strands' shell, file and Python tools work on a
sandbox object of ours?

| Step | Action |
|---|---|
| part a | Reach a Sprite's SSH port through the provider's proxy. Record whether `SshSandbox` can connect without the unsafe options flag, how long each command takes, and where the key must live |
| part b | Write a 60-line sandbox class implementing the six operations over a local folder. Bind `sandbox_shell`, `sandbox_file_editor` and `python_repl` to it. Run a scripted turn that writes a file, runs it and reads the output |
| 1 | In part b, confirm output streams while the command runs, and that wrapping each tool as a kernel tool keeps the before and after seams |

Pass: part b works with streaming. Part a is recorded either way.

Gates: `GatewaySandbox` in the kernel.

Fallback: if the tools cannot be bound to our object, the kernel defines its own three tools with the same names and
inputs and calls the tool gateway directly. Part a failing changes nothing: the Sprites backend uses the HTTP API.

## Trial 7: adding a secret at the exit gate

Question: can a proxy of ours add a credential to a sandbox's outgoing request without the sandbox seeing it?

| Step | Action |
|---|---|
| 1 | Run a forward proxy with a certificate authority the sandbox image trusts. Mark one test host as inspected |
| 2 | From a sandbox, call the host with a placeholder in a header using Python `requests`, `httpx`, `curl` and Node `fetch` |
| 3 | Confirm the host received the real value, the answer the script read has the value scrubbed, and the sandbox's environment and files hold only the placeholder |
| 4 | Call a host in tunnel mode and confirm the proxy sees the host name only |
| 5 | Try a client that pins the host's certificate and record the failure the script sees |
| 6 | Measure added time per request |

Pass: step 3 holds for all four clients, and the added time is under 20 ms at the median.

Gates: the exit gate's inspect mode and the `network_write` and `install_packages` approvals.

Fallback: secrets are not offered inside sandboxes; a script that needs a credentialed system calls a gateway tool from
inside the box instead (`ops.call`), which already keeps the secret outside.

## Trial 8: isolation level per install

Question: which wall does each kind of install get by default?

| Step | Action |
|---|---|
| 1 | On a small cloud host: run the sandbox image under Docker with gVisor. Run the escape and reach checks: host paths, the engine socket, the metadata address, other containers |
| 2 | Same host without gVisor, with the locked-down settings. Run the same checks. Try sandbox-runtime inside it |
| 3 | On a managed Kubernetes cluster on Azure and on one other cloud: install gVisor's runtime class; note whether Kata is available. Apply the namespace's policies and run the checks, including a request to the API server |
| 4 | Time a file-heavy job (unpack and parse a 500 MB archive) on each |

Pass: gVisor passes every check on Docker and on both clusters, and the file-heavy job takes at most twice its time
without gVisor.

Gates: the defaults in the Docker and Kubernetes backend specs, and the install guide.

Fallback: where gVisor cannot be installed, a Kubernetes install uses Kata on nodes that support it; a Docker install
stays on the locked-down level and is documented as single-firm only.

## Trial 9: start time and the warm pool

Question: how long does a person wait for the first command, and does a short function need its own engine?

| Step | Action |
|---|---|
| 1 | On each backend, measure 50 times: ensure to first command done, cold and with a warm computer |
| 2 | Measure a one-shot function run on each backend and on the WebAssembly engine |
| 3 | Find the pool size at which 95 of 100 first commands finish within 2 seconds at 10 new conversations a minute |

Pass: a warm first command is under 2 seconds at the 95th percentile on Docker and Kubernetes.

Gates: `OPS_SANDBOX_WARM_POOL`'s default, and whether the WebAssembly engine stays.

Fallback: WebAssembly stays for one-shot functions unless a backend runs one within 300 ms at the 95th percentile. A
slow first command is shown as "Starting the workspace" in chat.

## Trial 10: save, sleep and wake with 1 GB of files

Question: is copying changed files to storage after each turn fast enough?

| Step | Action |
|---|---|
| 1 | In a sandbox, create 1 GB across 2,000 files. Save. Record the time |
| 2 | Change 10 files. Save. Record the time |
| 3 | Destroy the computer. Ensure on another service instance. Record time to restore and compare hashes |
| 4 | Kill the service during a save; confirm the previous manifest is still current and the next save succeeds |

Pass: the second save is under 3 seconds, the restore under 60 seconds, and every hash matches.

Gates: the canonical-copy design in the sandbox service.

Fallback: saves run in the background after the reply is sent, and a turn that resumes before a save finishes waits for
it. If restore is too slow, large workspaces restore files on first read.

## Trial 11: a waiting run across an upgrade

Question: can a run's position be rebuilt from its journal?

| Step | Action |
|---|---|
| 1 | Write the replay prototype against the compiled graph: feed each journal row's port and output without running the step |
| 2 | For 30 definitions from the test suite, including joins, loops and child runs: run to a wait, delete the saved position, rebuild, finish. Compare the journal with an uninterrupted run |
| 3 | Change the engine's build value between the wait and the answer |

Pass: all 30 finish with identical journals and no step runs during a rebuild.

Gates: change 1 in workflow durability.

Fallback: saved positions are migrated by an upgrade step per build instead, and the reconciler keeps reporting what it
cannot migrate.

## Trial 12: a crash in the middle of a team, on both databases

Question: do engine-driven hand-overs and cycles survive a worker dying?

| Step | Action |
|---|---|
| 1 | Prototype hand-over ports and one cycle inside a group on the compiled graph, with scripted members |
| 2 | Run a five-turn team. Kill the worker during turn 3, and separately between turns 3 and 4 |
| 3 | Confirm one journal row per turn, no model call charged twice at the scripted gateway, and the same final output |
| 4 | Repeat on SQL Server |

Pass: step 3 holds in both kill positions on both databases.

Gates: the canvas team design.

Fallback: a cycle is compiled as a loop step that owns its members, which the engine already supports, and the canvas
draws it the same way.

## Trial 13: an agent step paused for approval

Question: can a workflow's agent step pause in mid-turn and continue the same turn after a person decides?

| Step | Action |
|---|---|
| 1 | With trial 1's code, return the pause from the agent port, record waiting on the run, store the loop state |
| 2 | Stop every process. Approve. Resume the step with the stored state |
| 3 | Confirm the write is sent once and earlier model answers are replayed, not charged |
| 4 | Send the approval by a signed link's confirm page and by an email reply; note what an attacker would need to forge each |

Pass: step 3 holds.

Gates: change 3 in workflow durability, and the email and Teams answer design.

Fallback: the step ends with its own port "needs approval" and a following review step re-runs the agent with the
decision. That costs a second turn but needs no saved loop state.

## Trial 14: the engine on SQL Server under load

Question: do the replaced statements hold without deadlocks?

| Step | Action |
|---|---|
| 1 | Replace the eleven baseline statements on a branch |
| 2 | Run 200 runs with 8 workers on SQL Server, each run with a wait and a resume |
| 3 | Count deadlocks, duplicate claims and duplicate journal rows |

Pass: no duplicate claim or row; deadlock retries under 1 percent of statements.

Gates: removing the engine's lines from the portable baseline.

Fallback: the statement that deadlocks keeps a SQL Server-specific form inside `ops_store.dialect`.

## Results

None yet.
