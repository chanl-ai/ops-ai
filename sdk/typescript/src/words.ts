/**
 * The Apps area in the words people see on screen (c-616): `apps`, `credentials`, `accounts`, `tools`, `resources` and
 * `usage`, each a few methods over the generated operations, which call the services' routes as they are. The Python
 * SDK has the same layer (sdk/python/src/ops_ai/_words.py).
 *
 * An app is named by its id on the Apps page: `plugin:<plugin id>`, `builtin:<name>`, or a custom app's connection id.
 * An account is a connection id (the team account, or another named one).
 */
import type { Raw, Resource } from './client.js';

type Obj = Record<string, any>;
const PLUGIN = 'plugin:';
// Where a resource's copy is made: document types in documents-service, everything else in agents-service.
const DOCUMENT_TYPE = 'document_type';

/** The plugin behind an app; only an app a plugin brings is turned on and off. */
export function pluginOf(app: string): string {
  if (!app.startsWith(PLUGIN)) throw new TypeError(`${app} is not an app a plugin brings; only those are turned on for a team`);
  return app.slice(PLUGIN.length);
}

// A built-in app is always there; any other reads connected only once its team account signed in or its test passed,
// which the card's `state` says; `status` is the account's display status.
const connected = (card: Obj) => card.kind === 'builtin' || card.state === 'connected';

/** The environment a run uses: the one given, else test when the app's account is set for it, else production when
 * that is. The page lists every environment, set or not. */
function environmentOf(page: Obj, given?: string): string {
  if (given) return given;
  const envs = page.connection?.environments ?? {};
  return envs.production?.set && !envs.test?.set ? 'production' : 'test';
}

function accountOf(page: Obj): string {
  if (!page.connection) throw new TypeError(`${page.card?.id} has no account yet; connect it first`);
  return String(page.connection.id);
}

const call = (raw: Raw, service: 'tools' | 'agents' | 'documents', id: string, args: Obj = {}): Promise<any> =>
  (raw[service] as unknown as Record<string, (a: Obj) => Promise<any>>)[id]!(args);

export class Apps {
  constructor(private readonly raw: Raw) {}

  /** The Apps page's cards; `connected` keeps only the connected ones (true) or only the rest (false). */
  async list({ connected: only }: { connected?: boolean } = {}): Promise<Obj[]> {
    const cards = (await call(this.raw, 'tools', 'connections_list_systems')) as Obj[];
    return cards.filter((c) => only === undefined || connected(c) === only);
  }

  get(app: string): Promise<Obj> {
    return call(this.raw, 'tools', 'connections_get_app', { path: { app_id: app } });
  }

  turnOn(app: string, fields: Obj = {}): Promise<Obj> {
    return call(this.raw, 'tools', 'plugins_set_team_plugin', { path: { plugin_id: pluginOf(app) }, body: { enabled: true, ...fields } });
  }

  turnOff(app: string): Promise<Obj> {
    return call(this.raw, 'tools', 'plugins_set_team_plugin', { path: { plugin_id: pluginOf(app) }, body: { enabled: false } });
  }

  /** The team's agents and workflows that use the app's tools: what turning it off stops. */
  users(app: string): Promise<Obj> {
    return call(this.raw, 'tools', 'plugins_app_users', { path: { plugin_id: pluginOf(app) } });
  }

  /** A custom app (rest, openapi or mcp): its connection, holding the base address and the key its tools use. */
  async addCustom(
    kind: string,
    name: string,
    o: { baseAddress: string; authKind?: string; settings?: Obj; secrets?: Record<string, string>; environment?: string },
  ): Promise<Obj> {
    if (kind === 'mcp') return call(this.raw, 'tools', 'connections_connect_mcp', { body: { name, url: o.baseAddress } });
    const made = await call(this.raw, 'tools', 'connections_create_connection', { body: { name, authKind: o.authKind ?? 'none' } });
    return call(this.raw, 'tools', 'connections_set_environment', {
      path: { connection_id: made.id, environment: o.environment ?? 'test' },
      body: { revision: made.revision, settings: { ...(o.settings ?? {}), baseUrl: o.baseAddress }, secretValues: o.secrets ?? {} },
    });
  }
}

/** How an app signs in: Ops AI's app, or the team's own client. */
export class Credentials {
  constructor(private readonly raw: Raw, private readonly apps: Apps) {}

  /** Each app's credential: Ops AI's app or the team's own client, its permissions, accounts and last test. */
  async list(): Promise<Obj[]> {
    return call(this.raw, 'tools', 'connections_list_app_credentials', {});
  }

  async set(app: string, o: { clientId: string; clientSecret?: string; environment?: string }): Promise<Obj> {
    const account = accountOf(await this.apps.get(app));
    const detail = await call(this.raw, 'tools', 'connections_get_connection', { path: { connection_id: account } });
    const body: Obj = { revision: detail.revision, settings: { clientId: o.clientId } };
    if (o.clientSecret) body.secretValues = { clientSecret: o.clientSecret };
    return call(this.raw, 'tools', 'connections_set_environment', {
      path: { connection_id: account, environment: o.environment ?? 'production' }, body,
    });
  }

  /** Test with my account: where to send the browser; `finish` hands back what the sign-in page was given. */
  async test(app: string, { environment = 'production' } = {}): Promise<Obj> {
    const account = accountOf(await this.apps.get(app));
    return call(this.raw, 'tools', 'connections_check_credential', { path: { connection_id: account }, body: { environment } });
  }

  async finish(app: string, o: { state: string; code: string }): Promise<Obj> {
    const account = accountOf(await this.apps.get(app));
    return call(this.raw, 'tools', 'connections_check_credential', { path: { connection_id: account }, body: o });
  }
}

export class Accounts {
  constructor(private readonly raw: Raw) {}

  /** Where to send the browser to sign in: the caller's own account, or (`team`) the team account. */
  connect(account: string, { environment = 'production', team = false } = {}): Promise<Obj> {
    const body = { environment, account: team ? 'team' : 'self' };
    return call(this.raw, 'tools', 'connections_start_sign_in', { path: { connection_id: account }, body });
  }

  test(account: string, { environment = 'production', team = false } = {}): Promise<Obj> {
    const body = { environment, account: team ? 'team' : 'self' };
    return call(this.raw, 'tools', 'connections_test_connection', { path: { connection_id: account }, body });
  }

  makeDefault(account: string): Promise<Obj> {
    return call(this.raw, 'tools', 'connections_pin_default', { path: { connection_id: account } });
  }

  /** The caller's own accounts on every app. */
  mine(): Promise<Obj[]> {
    return call(this.raw, 'tools', 'connections_my_connections');
  }

  /** The caller's own key on an app each person signs in to. */
  setKey(account: string, key: string, { environment = 'production' } = {}): Promise<Obj> {
    return call(this.raw, 'tools', 'connections_give_own_credentials', {
      path: { connection_id: account }, body: { environment, credentials: { key } },
    });
  }

  remove(account: string, { environment }: { environment?: string } = {}): Promise<unknown> {
    return call(this.raw, 'tools', 'connections_disconnect', { path: { connection_id: account }, query: { environment } });
  }
}

/** An app's tools. `get`, and `list` with no app, keep the tool modules' listing as it was. */
export class Tools {
  constructor(private readonly raw: Raw, private readonly apps: Apps, private readonly modules: Resource) {}

  async *list(app?: string, query: Record<string, unknown> = {}): AsyncGenerator<any> {
    if (app === undefined) {
      yield* this.modules.list(query);
      return;
    }
    yield* ((await this.apps.get(app)).tools ?? []) as Obj[];
  }

  get(id: string): Promise<any> {
    return this.modules.get(id);
  }

  /** Runs one of the app's tools: Mock reaches nothing; Real is the gateway's call, with every check. */
  async run(app: string, tool: string, input: Obj = {}, { real = false, environment }: { real?: boolean; environment?: string } = {}): Promise<Obj> {
    const page = await this.apps.get(app);
    const ids = (page.card?.moduleIds ?? []) as string[];
    let module = ids[0];
    if (ids.length !== 1) {
      const found = await Promise.all(ids.map((id) => call(this.raw, 'tools', 'tool_modules_get_module', { path: { module_id: id } })));
      module = found.find((m: Obj) => (m.operations ?? []).some((o: Obj) => o.name === tool))?.id;
    }
    if (!module) throw new TypeError(`no tool named ${tool} on ${app}`);
    return call(this.raw, 'tools', 'tool_modules_run_tool', {
      path: { module_id: module, operation: tool }, body: { mode: real ? 'real' : 'mock', input, environment: environmentOf(page, environment) },
    });
  }
}

/** The agents, skills, workflows and document types an app brings, each added to the team as a copy. */
export class Resources {
  constructor(private readonly raw: Raw) {}

  async list(app?: string): Promise<Obj[]> {
    const found = (await call(this.raw, 'tools', 'plugins_list_plugin_templates')) as Obj[];
    return found.filter((r) => app === undefined || r.source === app);
  }

  /** Adds a copy to the team: an item of `list`, or its source and id (`plugin:<plugin>:<id>`) with its kind. */
  add(resource: Obj | string, { kind, ...fields }: { kind?: string; [field: string]: unknown } = {}): Promise<Obj> {
    const id = typeof resource === 'string' ? resource : `${resource.source}:${resource.id}`;
    const k = typeof resource === 'string' ? kind : (resource.kind ?? kind);
    return call(this.raw, k === DOCUMENT_TYPE ? 'documents' : 'agents', 'resources_copy_resource', { path: { resource: id }, body: fields });
  }
}

export class Usage {
  constructor(private readonly raw: Raw) {}

  /** This team's tool calls, newest first, each saying whom it ran as. */
  async list(query: Record<string, unknown> = {}): Promise<Obj[]> {
    const found = await call(this.raw, 'tools', 'executions_list_executions', { query });
    return Array.isArray(found) ? found : (found?.data ?? []);
  }
}
