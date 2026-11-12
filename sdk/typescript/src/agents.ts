/** Agent lifecycle, chat and test over the generated agents operations. */
/* Agents talks to raw.agents only, so this file does not import the client. */

import { pageItems } from './transport.js';

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

export class Agents {
  constructor(private readonly raw: { agents: any }) {}

  async *list(query: Record<string, unknown> = {}) {
    let next: Record<string, unknown> | null = {};
    while (next) {
      const [items, more] = pageItems(await this.raw.agents.agents_list_agents({ query: { ...query, ...next } }));
      yield* items;
      next = more;
    }
  }

  get(id: string) {
    return this.raw.agents.agents_get_agent({ path: { agent_id: id } });
  }

  create(body: Record<string, unknown>) {
    return this.raw.agents.agents_create_agent({ body: body as never });
  }

  /** The operations an agent may be granted: published ones, as the agent page's picker lists them. */
  async toolOptions(search?: string): Promise<any[]> {
    const found = await this.raw.agents.agents_tool_options({ query: { search, limit: 100 } });
    return Array.isArray(found) ? found : (found?.data ?? found?.items ?? []);
  }

  /** Adds tools (their ids from `toolOptions`) to the agent's draft, keeping the ones it holds. Publish it for the grant to take effect. */
  async grantTools(id: string, tools: string[]) {
    const held: string[] = (await this.get(id)).toolIds ?? [];
    const wanted = [...held, ...tools.filter((t) => !held.includes(t))];
    return this.raw.agents.agents_update_agent({ path: { agent_id: id }, body: { toolIds: wanted } as never });
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
    return this.raw.agents.agents_create_agent({ body: body as never });
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
