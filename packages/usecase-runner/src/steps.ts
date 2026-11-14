/**
 * Named setup steps for a use case script. Each one calls the public TypeScript SDK (sdk/typescript), so a script that
 * uses them proves the SDK can do what a person's tools do. A step the SDK cannot do is a product gap: file a card
 * and show the step as open in the use case; do not add a raw HTTP call here. The table of steps is in
 * docs/usecases/README.md ("Shared steps").
 */
import { OpsAI } from '@chanl-ai/ops-ai';
import { AGENTS_PORT, DOCUMENTS_PORT, FILES_PORT, INVITED_PASSWORD, KB_PORT, PLATFORM_PORT, TOOLS_PORT, required } from './harness.ts';

export const PASSWORD = 'northfield-demo';
/** The dev seed's people (services/platform-service/seed), all in team_ops. */
export const PEOPLE = {
  james: 'j.richardson@harborpine.example',
  priya: 'p.shah@harborpine.example',
  maya: 'm.okafor@harborpine.example',
  sam: 's.adeyemi@harborpine.example',
  /** The workspace-wide admin: the only person who creates teams. */
  platform: 'w.kamau@harborpine.example',
} as const;

const here = (port: number) => `http://127.0.0.1:${port}`;

/** An SDK client pointed at the run's services, signed in with `session` fields from `options` when given. */
export function clientFor(options: ConstructorParameters<typeof OpsAI>[0] = {}): OpsAI {
  return new OpsAI({
    baseUrl: here(PLATFORM_PORT),
    services: { platform: here(PLATFORM_PORT), agents: here(AGENTS_PORT), tools: here(TOOLS_PORT), kb: here(KB_PORT), files: here(FILES_PORT), documents: here(DOCUMENTS_PORT) },
    ...options,
  });
}

/** Signs a seeded person in through the SDK and returns the client acting in `team` (`null`: in none, for the workspace admin). */
export function signInAs(email: string, { team = 'team_ops', password = PASSWORD }: { team?: string | null; password?: string } = {}): Promise<OpsAI> {
  return OpsAI.signIn(email, password, clientFor(team === null ? {} : { team }).config);
}

/**
 * Everything a run made, so a script can remove it at the end: `made.add('agent a1', () => ops.raw.agents.agents_delete_agent(...))`,
 * then `await made.cleanUp()`. Cleanup runs in reverse order and every failure is reported together.
 */
export function madeThings() {
  const undo: { what: string; run: () => Promise<unknown> }[] = [];
  return {
    add(what: string, run: () => Promise<unknown>) {
      undo.push({ what, run });
    },
    async cleanUp(): Promise<void> {
      const failed: string[] = [];
      for (const { what, run } of undo.splice(0).reverse()) {
        try {
          await run();
        } catch (e) {
          failed.push(`${what}: ${(e as Error).message}`);
        }
      }
      if (failed.length) throw new Error(`clean up left ${failed.length} behind: ${failed.join('; ')}`);
    },
  };
}

type Made = ReturnType<typeof madeThings>;

/**
 * A team made the way a workspace admin makes one: `admin` creates it with `firstAdmin` (a seeded person's email), who
 * invites each member with a role; each member accepts with a name and INVITED_PASSWORD. Returns the team and a
 * client for every member, acting in the team. Throws on any refusal.
 */
export async function makeTeam(
  admin: OpsAI,
  name: string,
  { firstAdmin, members = [], made }: { firstAdmin: string; members?: { email: string; role: string }[]; made?: Made },
): Promise<{ team: { id: string; name: string }; people: Record<string, OpsAI> }> {
  const team = (await admin.raw.platform.teams_create_team({ body: { name, admin: firstAdmin } })) as { id: string; name: string };
  // The platform deletes a team only 30 days after it is archived, so archived is as clean as a run can leave it.
  made?.add(`team ${name}`, () => admin.raw.platform.teams_archive_team({ path: { team_id: team.id } }));
  // The workspace admin is not a member of the team it makes; the team's first admin invites the others.
  const inTeam = await signInAs(firstAdmin, { team: team.id });
  const people: Record<string, OpsAI> = {};
  for (const { email, role } of members) {
    const sent = (await inTeam.raw.platform.members_invite_members({ body: { emails: [email], role } })) as { invites?: { token: string }[] };
    const token = sent.invites?.[0]?.token;
    if (!token) throw new Error(`inviting ${email} as ${role} returned no invitation`);
    const name = email.split('@')[0]!.replace(/\./g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
    const session = (await inTeam.raw.platform.invites_accept_invite({ path: { token }, body: { name, password: INVITED_PASSWORD } })) as { token: string; refreshToken: string };
    people[email] = clientFor({ team: team.id, accessToken: session.token, session: { accessToken: session.token, refreshToken: session.refreshToken } });
  }
  return { team, people };
}

/**
 * A knowledge base with one push source holding `items` (each indexed before this returns, as the push route does).
 * `owner` is the email of the person who answers for it.
 */
export async function addKnowledgeBase(
  ops: OpsAI,
  { name, owner, items, made }: { name: string; owner: string; items: { name: string; title?: string; text: string }[]; made?: Made },
): Promise<{ kbId: string; sourceId: string }> {
  const base = (await ops.raw.kb.knowledge_bases_create_knowledge_base({ body: { name, owner } as never })) as { id: string };
  made?.add(`knowledge base ${name}`, () => ops.raw.kb.knowledge_bases_remove_knowledge_base({ path: { kb_id: base.id } }));
  const source = (await ops.raw.kb.sources_create_source({ body: { type: 'push', name: `${name} feed`, kbIds: [base.id] } as never })) as { id: string };
  made?.add(`source of ${name}`, () => ops.raw.kb.sources_remove_source({ path: { source_id: source.id } }));
  for (const item of items) await ops.raw.kb.sources_put_item({ path: { source_id: source.id }, body: item as never });
  return { kbId: base.id, sourceId: source.id };
}

/**
 * An agent created and sent for publish; on a stack that auto-approves (the default) it is live when this returns.
 * Without `model` it uses the first chat alias the stack offers, since the aliases differ between stacks.
 * `toolIds` are granted before publish, so a skill naming those tools may be used in its chats.
 */
export async function publishAgent(
  ops: OpsAI,
  { name, role, model, instructions, toolIds, made }: { name: string; role: string; model?: string; instructions?: string; toolIds?: string[]; made?: Made },
): Promise<{ agentId: string; version: number }> {
  const alias = model ?? ((await ops.raw.agents.agents_list_model_aliases({})) as { name: string }[])[0]?.name;
  if (!alias) throw new Error('the stack offers no model alias to give the agent');
  const agent = (await ops.agents.create({ name, role, model: alias, instructions })) as { id: string; version?: number; draftVersion?: number };
  made?.add(`agent ${name}`, () => ops.raw.agents.agents_delete_agent({ path: { agent_id: agent.id } }));
  let version = agent.draftVersion ?? agent.version ?? 1;
  if (toolIds?.length) {
    const saved = (await ops.raw.agents.agents_update_agent({ path: { agent_id: agent.id }, body: { toolIds } as never })) as { version?: number };
    version = saved.version ?? version;
  }
  await ops.agents.publish(agent.id, 'Published by the use case', version);
  return { agentId: agent.id, version };
}

/** Starts a run of a workflow's current version and waits until it ends or stops at a human task (`taskId`). */
export async function runWorkflow(ops: OpsAI, workflowId: string, input: Record<string, unknown> = {}, options: { timeoutMs?: number } = {}) {
  const started = (await ops.runs.start(workflowId, { input })) as { runId: string };
  return ops.runs.wait(started.runId, options);
}

/** The auth headers of a seeded person's session, for the few requests a script still sends by hand (wrap them in `required`). */
export async function authHeaders(email: string, { team = 'team_ops' }: { team?: string | null } = {}): Promise<Record<string, string>> {
  const ops = await signInAs(email, { team });
  return { Authorization: `Bearer ${ops.config.session?.accessToken ?? ops.config.accessToken}`, ...(team ? { 'X-Team-Id': team } : {}), 'Content-Type': 'application/json' };
}

/**
 * The data of a setup `fetch` that must succeed: a refusal throws with its status, code and message, so the script
 * stops as setup instead of reading an empty body and failing later on a page that was never set up.
 */
export async function setup<T = any>(res: Response, what = new URL(res.url).pathname): Promise<T> {
  const text = await res.text();
  let data: unknown;
  try {
    data = (JSON.parse(text) as { data?: unknown }).data;
  } catch {
    // a non-JSON body is only acceptable on a refusal, which `required` reports below
  }
  if (res.ok && data === undefined && text) throw new Error(`setup request answered ${res.status} without data, ${what}: ${text.slice(0, 300)}`);
  return required<T>({ status: res.status, data, text }, what);
}

/** The Security team's admin allows the fake bank's host and the private range it serves on. */
export async function allowBank(security: OpsAI, bank: { host: string; range: string }, note: string): Promise<void> {
  await security.raw.tools.egress_add_host({ body: { value: bank.host, note } as never });
  await security.raw.tools.egress_add_range({ body: { value: bank.range, note } as never });
}

/**
 * Sam, the dev seed's Security admin, made an admin of `team` too (its admin invites him, he accepts as himself), because
 * team-wide policies such as the approvals switch are changed by a Security admin and apply to the team they act in.
 * Returns his client acting in `team`.
 */
export async function securityAdminOn(teamAdmin: OpsAI, team = 'team_ops'): Promise<OpsAI> {
  const sam = await signInAs(PEOPLE.sam, { team: 'team_security' });
  const sent = (await teamAdmin.raw.platform.members_invite_members({ body: { emails: [PEOPLE.sam], role: 'admin' } })) as { invites?: { token: string }[] };
  const token = sent.invites?.[0]?.token;
  if (!token) throw new Error('inviting the Security admin returned no invitation');
  await sam.raw.platform.invites_accept_invite({ path: { token }, body: { name: 'Sam Adeyemi' } as never });
  return signInAs(PEOPLE.sam, { team });
}

/**
 * Turns "ask before an agent changes anything in an app" on (a reviewer answers) or off for the team `admin` acts in,
 * as a Security admin does in Settings (`securityAdminOn`). The setting is per team: `admin` must act in the team under test.
 */
export async function setWriteApprovals(admin: OpsAI, on: boolean): Promise<void> {
  await admin.raw.platform.policies_set_policy({ path: { key: 'toolWritesNeedApproval' }, body: { value: on } as never });
}

/**
 * Lets the owner run a write from the workbench without a confirmation: the team asks no one before an agent changes an
 * app and its test runs of a live write do not ask the person either (`testRunsAsk` off). `admin` acts in the team.
 */
export async function setTestRunsDoNotAsk(admin: OpsAI): Promise<void> {
  await admin.raw.platform.policies_set_policy({
    path: { key: 'appChanges' },
    body: { value: { ask: false, answer: 'none', reviewerRole: null, testAccountsNeverAsk: true, testRunsAsk: false } } as never,
  });
}
