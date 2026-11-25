/** Agent lifecycle, chat and test over the generated agents operations. */
/* Agents talks to raw.agents only, so this file does not import the client. */

import { eachPage, eachRow, pageItems } from './transport.js';

export const PLANNED = 'This command is planned; the public API for it is not shipped.';

function replyText(data: unknown): string {
  if (typeof data === 'string') return data;
  if (!data || typeof data !== 'object') return '';
  const rec = data as Record<string, unknown>;
  for (const key of ['reply', 'content', 'text'] as const) {
    const value = rec[key];
    if (typeof value === 'string') return value;
  }
  return rec.data !== data ? replyText(rec.data) : '';
}

type Read = { version: number; digest?: string | null };

/** `fields` naming the copy they were made on: the `version` and `digest` of the agent or skill as `read`. The service refuses a save made from an older copy (`stale_base`), so it never writes over a change saved since. */
export const based = (fields: Record<string, unknown>, read: Read) => ({ ...fields, baseVersion: read.version, baseDigest: read.digest });

/** The eval-run body: no cases runs the saved ones, so `cases` is left out rather than sent empty. */
function evalBody(cases?: unknown[] | { cases: unknown[] }, trigger?: string) {
  const body: Record<string, unknown> = {};
  if (cases !== undefined) body.cases = Array.isArray(cases) ? cases : cases.cases;
  if (trigger !== undefined) body.trigger = trigger;
  return body;
}

export class Agents {
  constructor(private readonly raw: { agents: any }) {}

  list(query: Record<string, unknown> = {}) {
    return eachPage((page) => this.raw.agents.agents_list_agents({ query: page }), query);
  }

  get(id: string) {
    return this.raw.agents.agents_get_agent({ path: { agent_id: id } });
  }

  create(body: Record<string, unknown>) {
    return this.raw.agents.agents_create_agent({ body: body as never });
  }

  /** Saves `fields` on the agent's draft. `base` is the agent as last read, naming the copy the change was made on; left out, the agent is read first. A save from an older copy is refused with `stale_base`. */
  async update(id: string, fields: Record<string, unknown>, base?: Read) {
    // A list row carries no digest, so it cannot name a copy.
    const read = base?.digest ? base : await this.get(id);
    return this.raw.agents.agents_update_agent({ path: { agent_id: id }, body: based(fields, read) as never });
  }

  /** The operations an agent may be granted: published ones, as the agent page's picker lists them. */
  async toolOptions(search?: string): Promise<any[]> {
    const rows: any[] = [];
    for await (const row of eachRow((q) => this.raw.agents.agents_tool_options({ query: q as never }), { search, limit: 50 })) rows.push(row);
    return rows;
  }

  /** Adds tools (their ids from `toolOptions`) to the agent's draft, keeping the ones it holds. Publish it for the grant to take effect. */
  async grantTools(id: string, tools: string[]) {
    const agent = await this.get(id);
    const held: string[] = agent.toolIds ?? [];
    return this.update(id, { toolIds: [...held, ...tools.filter((t) => !held.includes(t))] }, agent);
  }

  /** What the agent's brief can mention with @, grouped by kind; each item says whether the agent holds it. `ids` (`kind:id` each) answers the labels of what a saved text names. */
  references(search: string, forAgent: string, query: { kind?: string; cursor?: string; limit?: number; ids?: string[] } = {}) {
    return this.raw.agents.agents_references_search({ query: { ...query, forAgent, search: search || undefined } as never });
  }

  /** Grants the agent a tool, knowledge base, skill, agent or workflow its brief mentions, as a new draft. `added` is empty when the agent already held it. */
  addReference(id: string, kind: 'tool' | 'knowledge' | 'skill' | 'agent' | 'workflow', refId: string) {
    return this.raw.agents.agents_add_reference({ path: { agent_id: id }, body: { kind, id: refId } as never });
  }

  /** The workspace's instruction section list: the stored one, or the default. Any signed-in person reads it. */
  instructionSections() {
    return this.raw.agents.agents_get_instruction_sections({});
  }

  /** Replaces the list (needs settings.manage). The server holds up to 8 presets per section and 40 sections. */
  setInstructionSections(listing: unknown) {
    return this.raw.agents.agents_put_instruction_sections({ body: listing as never });
  }

  /** Brings the default list back and returns it (needs settings.manage). */
  resetInstructionSections() {
    return this.raw.agents.agents_reset_instruction_sections({});
  }

  /** What stops the agent's newest draft from being published, each problem with the field it is in. */
  async publishCheck(id: string, version?: number) {
    version ??= (await this.get(id)).version;
    return this.raw.agents.agents_publish_check({ path: { agent_id: id }, query: { version } as never });
  }

  /** With no `cases`, runs the agent's saved cases on its newest version and keeps the run; the reply carries `gate` (`blocked`, `steps`) and `costUsd`. With cases it scores them and keeps nothing. `trigger` (manual or cli) says what started a kept run. */
  eval(id: string, cases?: unknown[] | { cases: unknown[] }, trigger?: 'manual' | 'cli') {
    return this.raw.agents.agents_create_eval_run({ path: { agent_id: id }, body: evalBody(cases, trigger) as never });
  }

  /** The agent's saved eval cases. */
  evalCases(id: string) {
    return this.raw.agents.assurance_agent_cases({ path: { agent_id: id } });
  }

  /** Adds cases to the agent's saved ones. */
  addEvalCases(id: string, cases: unknown[] | { cases: unknown[] }) {
    return this.raw.agents.assurance_add_agent_cases({ path: { agent_id: id }, body: evalBody(cases) as never });
  }

  /** The agent's kept runs, newest first, as rows without the case results. */
  evalRuns(id: string, query: { page?: number; pageSize?: number } = {}) {
    return this.raw.agents.assurance_agent_eval_runs({ path: { agent_id: id }, query: { page: 1, pageSize: 25, ...query } as never });
  }

  /** One kept run with its case results. */
  evalRun(runId: string) {
    return this.raw.agents.assurance_eval_run({ path: { run_id: runId } });
  }

  validate(definition: Record<string, unknown>) {
    const missing = (['name', 'role'] as const).filter((key) => !definition[key]);
    return {
      ok: missing.length === 0,
      checks: missing.map((field) => ({
        code: 'missing_field',
        field,
        message: `${field} is required`,
        level: 'error',
      })),
    };
  }

  apply(definition: Record<string, unknown>) {
    const body = {
      name: definition.name,
      role: definition.role,
      instructions: definition.instructions,
      model: definition.model,
      channels: definition.channels,
    };
    // The create route takes no brief; it is saved on the new agent's draft, as the Python SDK does.
    const later = Object.fromEntries(['brief', 'promptMode', 'patterns', 'modelSettings'].filter((k) => definition[k] !== undefined).map((k) => [k, definition[k]]));
    const made = this.raw.agents.agents_create_agent({ body: body as never });
    if (!Object.keys(later).length) return made;
    return made.then((agent: Read & { id: string }) => this.update(agent.id, later, agent));
  }

  async publish(id: string, note = '', version?: number) {
    // Left out, the version is the draft's current one, as the Python SDK does.
    version ??= (await this.get(id)).version;
    return this.raw.agents.agents_request_publish({ path: { agent_id: id }, body: { note, version } as never });
  }

  pause(id: string) {
    return this.raw.agents.agents_set_paused({ path: { agent_id: id }, body: { paused: true } as never });
  }

  async chat(id: string, message: string, threadId?: string) {
    let tid = threadId;
    if (!tid) {
      const created = (await this.raw.agents.threads_create_thread({ body: { graph: id.startsWith('agent:') ? id : `agent:${id}` } as never })) as {
        threadId?: string;
        id?: string;
      };
      tid = created.threadId ?? created.id;
    }
    if (!tid) throw new Error('thread create returned no id');
    const stream = await this.raw.agents.threads_stream_run({
      path: { thread_id: tid },
      body: { input: { message } } as never,
    });
    const events: unknown[] = [];
    if (stream && typeof (stream as AsyncIterable<unknown>)[Symbol.asyncIterator] === 'function') {
      for await (const event of stream as AsyncIterable<unknown>) events.push(event);
    } else if (stream) {
      events.push(stream);
    }
    let reply = '';
    const toolCalls: Record<string, any>[] = [];
    for (const event of events) {
      const rec = event && typeof event === 'object' ? (event as { data?: any }) : undefined;
      const data = rec?.data ?? event;
      const text = replyText(data);
      if (text) reply = text;
      const kind = data?.event;
      const payload = data?.data;
      const call = payload?.call ?? payload;
      const name = call?.name ?? call?.tool;
      if (name && ['tool_call', 'tool_start', 'tool_end'].includes(kind) && !toolCalls.some((c) => (c.name ?? c.tool) === name)) toolCalls.push({ ...call, name });
    }
    return { threadId: tid, reply, text: reply, events, toolCalls };
  }

  test(id: string, message: string) {
    return this.raw.agents.agents_test_agent({ path: { agent_id: id }, body: { message } as never });
  }

  trace(id: string, limit = 20) {
    return this.raw.agents.agents_recent_runs({ path: { agent_id: id }, query: { limit } });
  }
}
