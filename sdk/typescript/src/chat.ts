/**
 * Chat as the chat screen calls it: agents-service's `/v1/chat/*` routes. They are left out of the OpenAPI document, so
 * the generated layer has none of them; each is declared here as an operation and sent through the same transport. The
 * Python SDK has the same layer (sdk/python/src/ops_ai/_chat.py).
 *
 * A reply streams as server-sent events, each a JSON object with a `type`: `status`, `text` (a delta), `replace` (the
 * whole text so far), `tool_end`, `widget`, `error` and `done` (the stored message). `say` waits for the whole reply
 * and returns its events; `stream` yields them as they arrive.
 */
import { type CallArgs, type Operation, pageItems, type Transport } from './transport.js';

type Obj = Record<string, any>;

const LINKED = 'CONNECTION_NOT_LINKED';
const REASONS: Record<string, string> = { APP_OFF_FOR_TEAM: 'app_off', ACCOUNT_CHOICE_NEEDED: 'account_choice' };
export const WIDGET_ACTIONS = ['approve', 'reject', 'submit'] as const;

const op = (method: string, path: string, pathParams: string[] = [], stream = false): Operation => ({
  method,
  path,
  pathParams,
  query: [],
  headers: [],
  body: ['POST', 'PUT', 'PATCH'].includes(method) ? 'json' : null,
  stream,
});

const T = ['thread_id'];
const OPERATIONS = {
  agents: op('GET', '/v1/chat/agents'),
  default_agent: op('GET', '/v1/chat/default-agent'),
  threads: op('GET', '/v1/chat/threads'),
  create: op('POST', '/v1/chat/threads'),
  get: op('GET', '/v1/chat/threads/{thread_id}', T),
  update: op('PATCH', '/v1/chat/threads/{thread_id}', T),
  delete: op('DELETE', '/v1/chat/threads/{thread_id}', T),
  send: op('POST', '/v1/chat/threads/{thread_id}/messages', T, true),
  feedback: op('PUT', '/v1/chat/threads/{thread_id}/messages/{message_id}/feedback', [...T, 'message_id']),
  widget_action: op('POST', '/v1/chat/threads/{thread_id}/messages/{message_id}/widgets/{widget_id}/actions', [
    ...T,
    'message_id',
    'widget_id',
  ]),
  connectors: op('GET', '/v1/chat/threads/{thread_id}/connectors', T),
  set_connectors: op('PUT', '/v1/chat/threads/{thread_id}/connectors', T),
} as const;

/** New chat's body: no agent starts on the team's default; `test` is an agent page's Test panel. */
export function threadBody(agent?: string, o: { kbIds?: string[]; test?: boolean; title?: string } = {}): Obj {
  return {
    kbIds: [...(o.kbIds ?? [])],
    ...(o.title ? { title: o.title } : {}),
    ...(agent ? { agentId: agent } : {}),
    ...(o.test ? { test: true } : {}),
  };
}

/** A message, with the skill (and one of its parts) picked for this reply and its inputs, as the / menu sends it. */
export function sendBody(text: string, o: { skill?: string; part?: string; inputs?: Record<string, string> } = {}): Obj {
  const pick = { skillId: o.skill, ...(o.part ? { part: o.part } : {}), ...(o.inputs ? { inputs: o.inputs } : {}) };
  return { content: text, ...(o.skill ? { skill: pick } : {}) };
}

/** A widget's action as its buttons send it: approve, reject with a reason, or submit the form's values. */
export function actionBody(action: string, o: { reason?: string; values?: Record<string, string> } = {}): Obj {
  if (action === 'approve') return { type: 'approve' };
  if (action === 'reject') {
    if (!o.reason) throw new TypeError('a reject needs a reason, as the widget asks for one');
    return { type: 'reject', reason: o.reason };
  }
  if (action === 'submit') return { type: 'submit', values: { ...(o.values ?? {}) } };
  throw new TypeError(`a widget action is one of ${WIDGET_ACTIONS.join(', ')}, not ${action}`);
}

/** The card a failed tool call shows (the app to connect, or why it cannot be used), or null for any other call. */
export function connectCard(call: Obj): Obj | null {
  const out = call.output;
  let error = out && typeof out === 'object' ? out.error : undefined;
  if (error && typeof error.error === 'object' && error.error) error = error.error;
  if (call.status !== 'failed' || !error || typeof error !== 'object' || (error.code !== LINKED && !(error.code in REASONS))) {
    return null;
  }
  const reason = error.code in REASONS ? { reason: REASONS[error.code] } : {};
  return { ...(error.details ?? {}), ...reason, message: error.message ?? '' };
}

export class Chat {
  constructor(private readonly t: Transport) {}

  private call(name: keyof typeof OPERATIONS, args: CallArgs = {}): Promise<any> {
    return this.t.call('agents', OPERATIONS[name], args);
  }

  /** The agents New chat offers this person. */
  async agents(): Promise<Obj[]> {
    return pageItems(await this.call('agents'))[0] as Obj[];
  }

  defaultAgent(): Promise<Obj> {
    return this.call('default_agent');
  }

  /** One page of the person's conversations, newest first (`test: true` lists the agent Test panel's). */
  async threads(query: Record<string, unknown> = {}): Promise<Obj[]> {
    return pageItems(await this.call('threads', { query }))[0] as Obj[];
  }

  start(agent?: string, options: { kbIds?: string[]; test?: boolean; title?: string } = {}): Promise<Obj> {
    return this.call('create', { body: threadBody(agent, options) });
  }

  /** The conversation as the chat reads it: its messages, each with its tool calls and widgets. */
  get(thread: string): Promise<Obj> {
    return this.call('get', { path: { thread_id: thread } });
  }

  /** Sends a message and yields the reply's events as they stream; `skill`, `part` and `inputs` pick a skill for this reply only. */
  async *stream(
    thread: string,
    text: string,
    options: { skill?: string; part?: string; inputs?: Record<string, string> } = {},
  ): AsyncGenerator<Obj> {
    const events = (await this.call('send', { path: { thread_id: thread }, body: sendBody(text, options) })) as AsyncIterable<{
      data: unknown;
    }>;
    for await (const e of events) if (e.data && typeof e.data === 'object') yield e.data as Obj;
  }

  /** Sends a message and returns the reply's events once it has finished. */
  async say(
    thread: string,
    text: string,
    options: { skill?: string; part?: string; inputs?: Record<string, string> } = {},
  ): Promise<Obj[]> {
    const events: Obj[] = [];
    for await (const e of this.stream(thread, text, options)) events.push(e);
    return events;
  }

  /** A widget's action (`actionBody`); answers the widget in its new state. */
  act(thread: string, message: string, widget: string, action: Obj): Promise<Obj> {
    return this.call('widget_action', { path: { thread_id: thread, message_id: message, widget_id: widget }, body: action });
  }

  feedback(thread: string, message: string, feedback: string | null): Promise<unknown> {
    return this.call('feedback', { path: { thread_id: thread, message_id: message }, body: { feedback } });
  }

  /** The chat's connectors as its composer picker lists them. */
  async connectors(thread: string): Promise<Obj[]> {
    return [...((await this.call('connectors', { path: { thread_id: thread } })) as Obj).connectors];
  }

  /** Leaves these apps (by id) out of this chat; every other connector stays on. It only narrows. */
  async setConnectors(thread: string, { off }: { off: string[] }): Promise<Obj[]> {
    const made = (await this.call('set_connectors', { path: { thread_id: thread }, body: { off: [...off] } })) as Obj;
    return [...made.connectors];
  }

  remove(thread: string): Promise<unknown> {
    return this.call('delete', { path: { thread_id: thread } });
  }
}
