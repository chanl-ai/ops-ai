/**
 * `OpsAI`: the core nouns by name, `raw` for every other public operation, typed from the services' OpenAPI.
 *
 *   const ops = new OpsAI({ apiKey: 'ok_...', baseUrl: 'https://ops.example.com', team: 'team_claims' });
 *   for await (const agent of ops.agents.list()) console.log(agent);
 *   const started = await ops.runs.start('wf_card_dispute', { input: { account: '123' } });
 *   const run = await ops.runs.wait(started.runId);   // when it ends or stops at a human task
 *   if (run.taskId) await ops.tasks.decide(run.taskId, 'approve');
 */
import type { operations as AgentsOps } from './generated/agents.js';
import { agentsOperations } from './generated/agents-operations.js';
import type { operations as DocumentsOps } from './generated/documents.js';
import { documentsOperations } from './generated/documents-operations.js';
import type { operations as FilesOps } from './generated/files.js';
import { filesOperations } from './generated/files-operations.js';
import type { operations as KbOps } from './generated/kb.js';
import { kbOperations } from './generated/kb-operations.js';
import type { operations as PlatformOps } from './generated/platform.js';
import { platformOperations } from './generated/platform-operations.js';
import type { operations as ToolsOps } from './generated/tools.js';
import { toolsOperations } from './generated/tools-operations.js';
import { type CallArgs, type Config, type Operation, pageItems, result, type Service, Transport } from './transport.js';

type PathOf<O> = O extends { parameters: { path: infer P } } ? P : never;
type QueryOf<O> = O extends { parameters: { query?: infer Q } } ? Q : never;
type BodyOf<O> = O extends { requestBody?: { content: { 'application/json': infer B } } } ? B : never;
type OkOf<O> = O extends { responses: infer R }
  ? R extends { 200: { content: { 'application/json': infer J } } }
    ? J
    : R extends { 201: { content: { 'application/json': infer J } } }
      ? J
      : R extends { 202: { content: { 'application/json': infer J } } }
        ? J
        : unknown
  : unknown;
/** What an operation answers, without the `{success, data}` envelope. */
export type DataOf<O> = OkOf<O> extends { data: infer D } ? D : OkOf<O>;
/** An operation's arguments: its path parameters (required when it has any), query, extra headers and body. */
export type ArgsOf<O> = ([PathOf<O>] extends [never] ? { path?: undefined } : { path: PathOf<O> }) & {
  query?: QueryOf<O>;
  headers?: Record<string, string>;
  body?: BodyOf<O>;
};
export type RawService<Ops> = { [K in keyof Ops]: (args?: ArgsOf<Ops[K]>) => Promise<DataOf<Ops[K]>> };

function rawService<Ops>(t: Transport, service: Service, table: Record<string, Operation>): RawService<Ops> {
  return Object.fromEntries(
    Object.entries(table).map(([id, op]) => [id, (args: CallArgs = {}) => t.call(service, op, args)]),
  ) as RawService<Ops>;
}

/** Every public operation, by service and operationId: `ops.raw.agents.agents_list_agents({ query: { page: 2 } })`. */
export class Raw {
  readonly platform: RawService<PlatformOps>;
  readonly agents: RawService<AgentsOps>;
  readonly tools: RawService<ToolsOps>;
  readonly kb: RawService<KbOps>;
  readonly files: RawService<FilesOps>;
  readonly documents: RawService<DocumentsOps>;
  constructor(t: Transport) {
    this.platform = rawService(t, 'platform', platformOperations);
    this.agents = rawService(t, 'agents', agentsOperations);
    this.tools = rawService(t, 'tools', toolsOperations);
    this.kb = rawService(t, 'kb', kbOperations);
    this.files = rawService(t, 'files', filesOperations);
    this.documents = rawService(t, 'documents', documentsOperations);
  }
}

const TABLES: Record<Service, Record<string, Operation>> = {
  platform: platformOperations, agents: agentsOperations, tools: toolsOperations,
  kb: kbOperations, files: filesOperations, documents: documentsOperations,
};

interface Noun {
  service: Service;
  list?: string;
  get?: string;
  create?: string;
}

/** Which operation each verb of a resource calls; the Python SDK reads the same table (sdk/python/src/ops_ai/_client.py). */
export const NOUNS = {
  teams: { service: 'platform', list: 'teams_list_teams' },
  agents: { service: 'agents', list: 'agents_list_agents', get: 'agents_get_agent', create: 'agents_create_agent' },
  workflows: { service: 'agents', list: 'workflows_list_workflows', get: 'workflows_get_workflow' },
  threads: { service: 'agents', list: 'threads_list_threads', get: 'threads_thread_state', create: 'threads_create_thread' },
  cases: { service: 'agents', list: 'cases_list_cases', get: 'cases_get_case', create: 'cases_open_case' },
  tools: { service: 'tools', list: 'tool_modules_list_modules', get: 'tool_modules_get_module' },
  connections: {
    service: 'tools', list: 'connections_list_connections', get: 'connections_get_connection',
    create: 'connections_create_connection',
  },
  knowledge: {
    service: 'kb', list: 'knowledge_bases_list_knowledge_bases', get: 'knowledge_bases_get_knowledge_base',
    create: 'knowledge_bases_create_knowledge_base',
  },
  files: { service: 'files', list: 'files_list_files', get: 'files_get_file' },
  runs: { service: 'agents', list: 'workflows_list_engine_runs', get: 'workflows_get_engine_run' },
  tasks: { service: 'agents', list: 'reviews_list_reviews', get: 'reviews_get_review' },
} as const satisfies Record<string, Noun>;

export class Resource {
  constructor(
    protected readonly t: Transport,
    protected readonly noun: Noun,
  ) {}

  protected call(verb: 'list' | 'get' | 'create', args: CallArgs): Promise<unknown> {
    const id = this.noun[verb];
    if (!id) throw new TypeError(`${verb} is not offered here; use ops.raw.${this.noun.service}`);
    return this.t.call(this.noun.service, TABLES[this.noun.service][id]!, args);
  }

  /** Every item, page after page, whichever paging the route uses. */
  async *list(query: Record<string, unknown> = {}): AsyncGenerator<any> {
    let next: Record<string, unknown> | null = {};
    while (next) {
      const [items, more] = pageItems(await this.call('list', { query: { ...query, ...next } }));
      yield* items;
      next = more;
    }
  }

  get(id: string): Promise<any> {
    const op = TABLES[this.noun.service][this.noun.get ?? '']!;
    return this.call('get', { path: { [op.pathParams[0]!]: id } });
  }

  create(body: unknown): Promise<any> {
    return this.call('create', { body });
  }
}

/** A run is over in these states; `waiting` means it stopped at a step that waits on a person or another system. */
export const TERMINAL = ['succeeded', 'failed', 'cancelled'] as const;

type RunDetail = DataOf<AgentsOps['workflows_get_engine_run']>;
/** A run, with `taskId` when it waits on a human task, so the next call is `tasks.decide`. */
export type WaitedRun = RunDetail & { taskId?: string };

export class Runs extends Resource {
  constructor(t: Transport, private readonly raw: Raw) {
    super(t, NOUNS.runs);
  }

  /** Starts a run of the workflow's current version; `fields` takes `version`, `runKey` and `mode`. */
  start(workflowId: string, options: { input?: Record<string, unknown>; [field: string]: unknown } = {}) {
    const { input, ...fields } = options;
    return this.raw.agents.workflows_start_engine_run({ body: { workflowId, input: input ?? {}, ...fields } as never });
  }

  /** The run once it has ended or stopped at a human task (then `taskId` names the task). */
  async wait(runId: string, { timeoutMs = 600_000, intervalMs = 1000 } = {}): Promise<WaitedRun> {
    const deadline = Date.now() + timeoutMs;
    for (;;) {
      const run = await this.raw.agents.workflows_get_engine_run({ path: { run_id: runId } });
      if ((TERMINAL as readonly string[]).includes(run.status) || run.status === 'waiting') {
        const task = (run.waiting?.payload as { review_id?: string } | undefined)?.review_id;
        return task ? { ...run, taskId: task } : run;
      }
      if (Date.now() > deadline) throw new Error(`run ${runId} is still ${run.status} after ${timeoutMs / 1000}s`);
      await new Promise((r) => setTimeout(r, intervalMs));
    }
  }

  /** The run's events as they happen, until it ends or waits. */
  stream(runId: string, after?: string) {
    const op = agentsOperations.workflows_engine_run_events;
    return this.t.stream('agents', op, { path: { run_id: runId }, query: { after, follow: true } });
  }

  cancel(runId: string) {
    return this.raw.agents.workflows_cancel_engine_run({ path: { run_id: runId } });
  }
}

/** Human tasks. The API calls them reviews (`reviews_*`); the console and this SDK say task. */
export class Tasks extends Resource {
  constructor(t: Transport, private readonly raw: Raw) {
    super(t, NOUNS.tasks);
  }

  /** Sends one of the actions the task offers. The approval token is the server's to issue; nothing here makes one. */
  decide(taskId: string, decision: string, fields: { reason?: string; [field: string]: unknown } = {}) {
    return this.raw.agents.reviews_decide({ path: { thread_id: taskId }, body: { decision, ...fields } as never });
  }
}

export class Files extends Resource {
  constructor(t: Transport, private readonly raw: Raw) {
    super(t, NOUNS.files);
  }

  /** Uploads bytes the way the console does: a ticket, the bytes, then complete. */
  async upload(name: string, content: Uint8Array<ArrayBuffer>, { mime, purpose }: { mime: string; purpose: string }) {
    const hash = new Uint8Array(await crypto.subtle.digest('SHA-256', content));
    const digest = Array.from(hash, (b) => b.toString(16).padStart(2, '0')).join('');
    const ticket = (await this.raw.files.files_create_upload({
      body: { name, size: content.byteLength, mime, purpose, digest } as never,
      headers: { 'Idempotency-Key': `sdk-${digest.slice(0, 32)}` },
    })) as { fileId: string; uploadUrl?: string; headers?: Record<string, string> };
    if (ticket.uploadUrl) {
      const put = await fetch(ticket.uploadUrl, {
        method: 'PUT',
        headers: { ...this.t.headers(), ...(ticket.headers ?? {}) },
        body: content,
      });
      if (put.status !== 409) await result(put); // 409: an earlier call stored these bytes under the same key
    }
    const done = (await this.raw.files.files_complete_upload({ path: { file_id: ticket.fileId } })) as Record<string, unknown>;
    return (done.file as Record<string, unknown> | undefined) ?? done;
  }
}

export class Knowledge extends Resource {
  constructor(t: Transport, private readonly raw: Raw) {
    super(t, NOUNS.knowledge);
  }

  search(body: ArgsOf<KbOps['knowledge_bases_search_knowledge']>['body']) {
    return this.raw.kb.knowledge_bases_search_knowledge({ body });
  }
}

export class OpsAI {
  readonly config: Config;
  readonly raw: Raw;
  readonly teams: Resource;
  readonly agents: Resource;
  readonly workflows: Resource;
  readonly threads: Resource;
  readonly cases: Resource;
  readonly tools: Resource;
  readonly connections: Resource;
  readonly knowledge: Knowledge;
  readonly files: Files;
  readonly runs: Runs;
  readonly tasks: Tasks;

  /** Options win over OPS_BASE_URL, OPS_API_KEY and OPS_TEAM. */
  constructor(options: Partial<Config> = {}) {
    // Node's environment when there is one; a browser has none.
    const env = (globalThis as { process?: { env: Record<string, string | undefined> } }).process?.env ?? {};
    const baseUrl = options.baseUrl ?? env.OPS_BASE_URL;
    if (!baseUrl) throw new TypeError('No Ops AI address: pass baseUrl or set OPS_BASE_URL');
    this.config = { ...options, baseUrl, apiKey: options.apiKey ?? env.OPS_API_KEY, team: options.team ?? env.OPS_TEAM };
    const t = new Transport(this.config);
    this.raw = new Raw(t);
    this.teams = new Resource(t, NOUNS.teams);
    this.agents = new Resource(t, NOUNS.agents);
    this.workflows = new Resource(t, NOUNS.workflows);
    this.threads = new Resource(t, NOUNS.threads);
    this.cases = new Resource(t, NOUNS.cases);
    this.tools = new Resource(t, NOUNS.tools);
    this.connections = new Resource(t, NOUNS.connections);
    this.knowledge = new Knowledge(t, this.raw);
    this.files = new Files(t, this.raw);
    this.runs = new Runs(t, this.raw);
    this.tasks = new Tasks(t, this.raw);
  }

  /** A client acting as a person. A session carries the teams the person was in when it was made. */
  static async signIn(email: string, password: string, options: Partial<Config> = {}): Promise<OpsAI> {
    const session = await new OpsAI(options).raw.platform.auth_sign_in({ body: { email, password } });
    return new OpsAI({ ...options, accessToken: session.token });
  }

  /** The same credential and address, acting in another team. */
  withTeam(team: string): OpsAI {
    return new OpsAI({ ...this.config, team });
  }
}
