/**
 * The Apps area in the words people see on screen: `apps`, `credentials`, `accounts`, `tools`, `resources` and
 * `usage`, each a few methods over the generated operations, which call the services' routes as they are. The Python
 * SDK has the same layer (sdk/python/src/ops_ai/_words.py).
 *
 * An app is named by its id on the Apps page: `plugin:<plugin id>`, `builtin:<name>`, or a custom app's id. An app's
 * accounts are the team account and any other named one, a sandbox among them (the account a test run uses); an
 * account method left without `account` acts on the app's default account.
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
// Connected is the card's appGroup `on`: the app works for the caller (tools-service decides it).
const connected = (card: Obj) => card.kind === 'builtin' || card.appGroup === 'on';

function accountOf(page: Obj): string {
  if (!page.connection) throw new TypeError(`${page.card?.id} has no account yet; connect it first`);
  return String(page.connection.id);
}

const call = (raw: Raw, service: 'tools' | 'agents' | 'documents' | 'kb' | 'platform', id: string, args: Obj = {}): Promise<any> =>
  (raw[service] as unknown as Record<string, (a: Obj) => Promise<any>>)[id]!(args);

const at = (app: string, account: string) => ({ app_id: app, account_id: account });

function picked(found: Obj, names?: string[]): Obj[] {
  const ops = (found.operations ?? []) as Obj[];
  if (!names) return ops;
  const missing = names.filter((n) => !ops.some((o) => o.name === n));
  // A typo would otherwise import less than the builder ticked.
  if (missing.length) throw new TypeError(`the document has no operation named ${missing.join(', ')}`);
  return ops.filter((o) => names.includes(o.name));
}

const sourceOf = (specUrl: string, connectionId?: string) => ({ kind: 'openapi', specUrl, ...(connectionId ? { connectionId } : {}) });

const rowsOf = (found: any): Obj[] => (Array.isArray(found) ? found : (found?.data ?? []));

/** The team's secrets (Settings > Secrets). A value goes in and is never read back: no answer carries it. */
export class Secrets {
  constructor(private readonly raw: Raw) {}

  async list(): Promise<Obj[]> {
    return rowsOf(await call(this.raw, 'tools', 'secrets_list_secrets'));
  }

  /** Stores a secret as the team's; `teams` also shares it with other teams of the caller. */
  create(name: string, value: string, { teams }: { teams?: string[] } = {}): Promise<Obj> {
    return call(this.raw, 'tools', 'secrets_create_secret', { body: { name, value, ...(teams?.length ? { teams } : {}) } });
  }

  rotate(name: string, value: string): Promise<Obj> {
    return call(this.raw, 'tools', 'secrets_rotate_secret', { path: { name }, body: { value } });
  }

  rename(name: string, newName: string): Promise<Obj> {
    return call(this.raw, 'tools', 'secrets_rename_secret', { path: { name }, body: { name: newName } });
  }

  delete(name: string): Promise<unknown> {
    return call(this.raw, 'tools', 'secrets_delete_secret', { path: { name } });
  }
}

/** The hosts and address ranges tools may reach (Settings > Egress); only a Security admin changes them. */
export class Egress {
  constructor(private readonly raw: Raw) {}

  list(): Promise<Obj> {
    return call(this.raw, 'tools', 'egress_allow_list');
  }

  allowHost(host: string, note = ''): Promise<Obj> {
    return call(this.raw, 'tools', 'egress_add_host', { body: { value: host, note } });
  }

  allowRange(cidr: string, note = ''): Promise<Obj> {
    return call(this.raw, 'tools', 'egress_add_range', { body: { value: cidr, note } });
  }

  removeHost(host: string): Promise<Obj> {
    return call(this.raw, 'tools', 'egress_remove_host', { body: { value: host } });
  }

  removeRange(cidr: string): Promise<Obj> {
    return call(this.raw, 'tools', 'egress_remove_range', { body: { value: cidr } });
  }
}

/** The team's settings a Security admin changes (Settings > Policies), such as `toolWritesNeedApproval`. They belong to the team the client acts in. */
export class Policies {
  constructor(private readonly raw: Raw) {}

  get(key: string): Promise<Obj> {
    return call(this.raw, 'platform', 'policies_get_policy', { path: { key } });
  }

  set(key: string, value: unknown): Promise<Obj> {
    return call(this.raw, 'platform', 'policies_set_policy', { path: { key }, body: { value } });
  }
}

export class Apps {
  constructor(private readonly raw: Raw) {}

  /** The Apps page's cards; `connected` keeps only the connected ones (true) or only the rest (false). */
  async list({ connected: only }: { connected?: boolean } = {}): Promise<Obj[]> {
    const cards = (await call(this.raw, 'tools', 'apps_list_apps')) as Obj[];
    return cards.filter((c) => only === undefined || connected(c) === only);
  }

  get(app: string): Promise<Obj> {
    return call(this.raw, 'tools', 'apps_get_app', { path: { app_id: app } });
  }

  turnOn(app: string, fields: Obj = {}): Promise<Obj> {
    pluginOf(app);
    return call(this.raw, 'tools', 'apps_set_team_app', { path: { app_id: app }, body: { enabled: true, ...fields } });
  }

  turnOff(app: string): Promise<Obj> {
    pluginOf(app);
    return call(this.raw, 'tools', 'apps_set_team_app', { path: { app_id: app }, body: { enabled: false } });
  }

  /** The team's agents and workflows that use the app's tools: what turning it off stops. */
  users(app: string): Promise<Obj> {
    pluginOf(app);
    return call(this.raw, 'tools', 'apps_app_users', { path: { app_id: app } });
  }

  /** A custom app (rest, openapi or mcp) as its first account, holding the base address and the key its tools use. */
  async addCustom(
    kind: string,
    name: string,
    o: { baseAddress: string; authKind?: string; settings?: Obj; secrets?: Record<string, string> },
  ): Promise<Obj> {
    if (kind === 'mcp') return call(this.raw, 'tools', 'apps_add_app', { body: { name, serverUrl: o.baseAddress } });
    const made = await call(this.raw, 'tools', 'apps_add_app', { body: { name, authKind: o.authKind ?? 'none' } });
    return call(this.raw, 'tools', 'apps_change_account', {
      path: at(made.id, made.id),
      body: { revision: made.revision, settings: { ...(o.settings ?? {}), baseUrl: o.baseAddress }, secretValues: o.secrets ?? {} },
    });
  }
}

/** How an app signs in: Ops AI's app, or one of the team's own clients (app credentials). */
export class Credentials {
  constructor(private readonly raw: Raw, private readonly apps: Apps) {}

  /** The team's app credentials and Ops AI's app of each app using it: permissions, accounts and last test. */
  async list(): Promise<Obj[]> {
    return call(this.raw, 'tools', 'apps_list_app_credentials', {});
  }

  /** One app credential with the accounts signing in with it. */
  async get(credential: string): Promise<Obj> {
    return call(this.raw, 'tools', 'apps_get_app_credential', { path: { credential_id: credential } });
  }

  /** The team's own client for an app: its client id, secret and permissions (all when left out), with no account
   * needed. Accounts pick it by its id (`set`, or credentialId when connected); no answer carries the secret. */
  async create(app: string, o: { clientId: string; clientSecret?: string; name?: string; scopes?: string[] }): Promise<Obj> {
    const body: Obj = { app, clientId: o.clientId };
    if (o.clientSecret) body.clientSecret = o.clientSecret;
    if (o.name) body.name = o.name;
    if (o.scopes) body.scopes = o.scopes;
    return call(this.raw, 'tools', 'apps_create_app_credential', { body });
  }

  /** A new client secret for the team's own client; every account on it keeps it. */
  async replaceSecret(credential: string, clientSecret: string): Promise<Obj> {
    return call(this.raw, 'tools', 'apps_set_app_credential_secret', { path: { credential_id: credential }, body: { clientSecret } });
  }

  /** Signs the app's account (its default unless `account`) in with one of the team's credentials, or with null,
   * Ops AI's app. The account signs in again. */
  async set(app: string, credential: string | null, { account }: { account?: string } = {}): Promise<Obj> {
    const found = account ?? accountOf(await this.apps.get(app));
    const detail = await call(this.raw, 'tools', 'apps_get_account', { path: at(app, found) });
    return call(this.raw, 'tools', 'apps_change_account', { path: at(app, found), body: { revision: detail.revision, credentialId: credential } });
  }

  /** Test with my account: where to send the browser; `finish` hands back what the sign-in page was given. */
  async test(app: string, { account }: { account?: string } = {}): Promise<Obj> {
    const found = account ?? accountOf(await this.apps.get(app));
    return call(this.raw, 'tools', 'apps_check_credential', { path: at(app, found), body: {} });
  }

  async finish(app: string, o: { state: string; code: string; account?: string }): Promise<Obj> {
    const found = o.account ?? accountOf(await this.apps.get(app));
    return call(this.raw, 'tools', 'apps_check_credential', { path: at(app, found), body: { state: o.state, code: o.code } });
  }
}

export class Accounts {
  constructor(private readonly raw: Raw, private readonly apps: Apps) {}

  private async account(app: string, account?: string): Promise<string> {
    return account ?? accountOf(await this.apps.get(app));
  }

  /** Another account of an app the team has: a sandbox, which test runs use, or another named one; `fields` are a
   * plugin account's turn-on fields (credentialId, credentials, signIn...). */
  add(app: string, name: string, { sandbox = false, ...fields }: { sandbox?: boolean; [field: string]: unknown } = {}): Promise<Obj> {
    return call(this.raw, 'tools', 'apps_add_account', { path: { app_id: app }, body: { name, sandbox, ...fields } });
  }

  /** Where to send the browser to sign in: the caller's own account, or (`team`) the team account. */
  async connect(app: string, { account, team = false }: { account?: string; team?: boolean } = {}): Promise<Obj> {
    const body = { account: team ? 'team' : 'self' };
    return call(this.raw, 'tools', 'apps_start_sign_in', { path: at(app, await this.account(app, account)), body });
  }

  async test(app: string, { account, team = false }: { account?: string; team?: boolean } = {}): Promise<Obj> {
    const body = { account: team ? 'team' : 'self' };
    return call(this.raw, 'tools', 'apps_test_account', { path: at(app, await this.account(app, account)), body });
  }

  makeDefault(app: string, account: string): Promise<Obj> {
    return call(this.raw, 'tools', 'apps_pin_default', { path: at(app, account) });
  }

  /** The caller's own accounts on every app. */
  mine(): Promise<Obj[]> {
    return call(this.raw, 'tools', 'apps_my_accounts');
  }

  /** The caller's own key on an account each person signs in to. */
  setKey(account: string, key: string): Promise<Obj> {
    return call(this.raw, 'tools', 'apps_give_own_credentials', { path: { account_id: account }, body: { credentials: { key } } });
  }

  remove(account: string): Promise<unknown> {
    return call(this.raw, 'tools', 'apps_disconnect', { path: { account_id: account } });
  }
}

/** The caller's connectors, as Connectors › Mine lists them: one row per app that acts as them. */
export class Connectors {
  constructor(private readonly raw: Raw) {}

  /** One row per app: what it can do as the caller, whom it signs in as, its app's state for them (appState, as
   * GET /v1/apps answers it) and who acts next (appGroup), and its accounts as a count with a primary. */
  list(): Promise<Obj[]> {
    return call(this.raw, 'tools', 'apps_my_connections');
  }

  async get(app: string): Promise<Obj> {
    const found = (await this.list()).find((c) => c.appId === app || String(c.name).toLowerCase() === app.toLowerCase());
    if (!found) throw new TypeError(`${app} is not one of your connectors`);
    return found;
  }

  /** Ends the caller's own sign-in on the app's primary account, or on `account`. */
  async disconnect(app: string, { account }: { account?: string } = {}): Promise<void> {
    const connector = await this.get(app);
    const target = account ?? (connector.primaryAccountId as string | null | undefined);
    if (!target) throw new TypeError(`${connector.name} has no account of yours to disconnect`);
    await call(this.raw, 'tools', 'apps_disconnect', { path: { account_id: target } });
  }

  /** Starts a sign-in and returns where to send the browser (`authorizeUrl`). Pass `link`, the connect link a call for
   * the caller was answered with, or `app` to sign in from the connector itself. */
  async connect(app?: string, { link, account, team = false }: { link?: string; account?: string; team?: boolean } = {}): Promise<Obj> {
    if (link) return call(this.raw, 'tools', 'apps_open_connect_link', { body: { link } });
    if (!app) throw new TypeError('connect needs an app or a connect link');
    const connector = await this.get(app);
    const target = account ?? (connector.primaryAccountId as string | null | undefined) ?? connector.appId;
    return call(this.raw, 'tools', 'apps_start_sign_in', {
      path: { app_id: connector.appId, account_id: target },
      body: { account: team ? 'team' : 'self' },
    });
  }

  /** Finishes the sign-in the browser came back from, with the `state` and `code` in the address it returned to. */
  finish(state: string, code?: string, { error }: { error?: string } = {}): Promise<Obj> {
    return call(this.raw, 'tools', 'apps_finish_sign_in', { body: { state, ...(code ? { code } : {}), ...(error ? { error } : {}) } });
  }

  /** The caller's own accounts on every app. */
  accounts(): Promise<Obj[]> {
    return call(this.raw, 'tools', 'apps_my_accounts');
  }
}

/** What belongs to the caller themselves. */
export class Me {
  readonly connectors: Connectors;
  constructor(raw: Raw) {
    this.connectors = new Connectors(raw);
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
    // Left out, a Real run is a test run: the app's sandbox account when it has one.
    const body: Obj = { mode: real ? 'real' : 'mock', input, ...(environment ? { environment } : {}) };
    return call(this.raw, 'tools', 'tool_modules_run_tool', { path: { module_id: module, operation: tool }, body });
  }

  /** An empty tool module for the team's builders to import operations into. */
  createModule(name: string, displayName: string, { type = 'openapi' }: { type?: string } = {}): Promise<Obj> {
    return call(this.raw, 'tools', 'tool_modules_create_blank_module', { body: { name, displayName, type } });
  }

  /** Reads an OpenAPI document and lists the operations it would bring, each with the access its method gives it. Nothing is saved. */
  discover(specUrl: string, { connectionId }: { connectionId?: string } = {}): Promise<Obj> {
    return call(this.raw, 'tools', 'tool_modules_discover', { body: sourceOf(specUrl, connectionId) });
  }

  /** Imports the ticked operations (all when `operations` is left out) of an OpenAPI document into a module's draft. */
  async importOpenapi(module: string, specUrl: string, operations?: string[], { connectionId }: { connectionId?: string } = {}): Promise<Obj> {
    const source = sourceOf(specUrl, connectionId);
    const found = await call(this.raw, 'tools', 'tool_modules_discover', { body: source });
    return call(this.raw, 'tools', 'tool_modules_import_operations', { path: { module_id: module }, body: { source, operations: picked(found, operations) } });
  }

  /** Asks the Security team to review the module's draft. */
  requestReview(module: string, note = ''): Promise<Obj> {
    return call(this.raw, 'tools', 'tool_modules_request_review', { path: { module_id: module }, body: { note } });
  }

  /** The id of the security review a module detail (from `requestReview` or `get`) waits on. Security does not see the owner's module, so the owner passes this id on. */
  reviewOf(module: Obj): string {
    const waiting = ((module.versions ?? []) as Obj[]).find((v) => v.status === 'in_review' && v.reviewId);
    if (!waiting) throw new TypeError('this tool module has no version waiting on a security review; request one first');
    return String(waiting.reviewId);
  }

  /** The Security team's answer to a module's review; `approved` publishes the module. */
  decideReview(review: string, decision = 'approved', { reason }: { reason?: string } = {}): Promise<Obj> {
    return call(this.raw, 'agents', 'reviews_decide_publish_request', { path: { request_id: review }, body: { decision, ...(reason ? { reason } : {}) } });
  }

  publishVersion(module: string, note = ''): Promise<Obj> {
    return call(this.raw, 'tools', 'tool_modules_publish_version', { path: { module_id: module }, body: { note } });
  }

  /** `run` for a module that is not an app: the test panel's call on the module itself. */
  runModule(module: string, tool: string, input: Obj = {}, { real = false, environment }: { real?: boolean; environment?: string } = {}): Promise<Obj> {
    const body: Obj = { mode: real ? 'real' : 'mock', input, ...(environment ? { environment } : {}) };
    return call(this.raw, 'tools', 'tool_modules_run_tool', { path: { module_id: module, operation: tool }, body });
  }
}

/** A copy's kind, record id and resource id, from an answer of `add`, a row of `list`, or the copy itself. */
function copyOf(made: Obj): { kind: string; record: string; resource: string } {
  const c = made.copy && typeof made.copy === 'object' ? made.copy : made;
  if (!c.recordId) throw new TypeError('no copy here: add the resource to the team first');
  return { kind: String(c.kind), record: String(c.recordId), resource: `${c.source}:${c.templateId}` };
}

// The delete each kind's copy goes through, by the service that keeps it, and the path field naming the record.
const DELETES: Record<string, ['agents' | 'documents' | 'kb', string, string]> = {
  agent: ['agents', 'agents_delete_agent', 'agent_id'],
  skill: ['agents', 'agents_delete_skill', 'skill_id'],
  workflow: ['agents', 'workflows_delete_definition', 'workflow_id'],
  [DOCUMENT_TYPE]: ['documents', 'document_types_delete_type', 'type_id'],
  knowledge_source: ['kb', 'sources_remove_source', 'source_id'],
};

/** The agents, skills, workflows, document types and knowledge sources an app brings, each added to the team as a copy. */
export class Resources {
  constructor(private readonly raw: Raw) {}

  /** The app's Resources tab: each resource with its state for the team, the team's copy, and whether you may add it. */
  list(app: string): Promise<Obj[]> {
    return call(this.raw, 'tools', 'plugins_list_app_resources', { path: { app_id: app } });
  }

  /** The preview of adding several: what each brings, what the team holds, the bindings and refusals, in add order. */
  plan(resources: Array<Obj | string>): Promise<Obj> {
    const ids = resources.map((r) => (typeof r === 'string' ? r : `${r.source}:${r.id}`));
    return call(this.raw, 'agents', 'resources_plan_resources', { body: { resources: ids } });
  }

  /** Adds a copy to the team: an item of `list`, or its source and id (`plugin:<plugin>:<id>`) with its kind. */
  add(resource: Obj | string, { kind, ...fields }: { kind?: string; [field: string]: unknown } = {}): Promise<Obj> {
    const id = typeof resource === 'string' ? resource : `${resource.source}:${resource.id}`;
    const k = typeof resource === 'string' ? kind : (resource.kind ?? kind);
    return call(this.raw, k === DOCUMENT_TYPE ? 'documents' : 'agents', 'resources_copy_resource', { path: { resource: id }, body: fields });
  }

  /** Takes the app's current template as a new version of the copy; an edited copy is refused until `confirm`. */
  update(copy: Obj, { confirm = false }: { confirm?: boolean } = {}): Promise<Obj> {
    const c = copyOf(copy);
    return call(this.raw, c.kind === DOCUMENT_TYPE ? 'documents' : 'agents', 'resources_take_update', { path: { resource: c.resource, copy: c.record }, body: { confirm } });
  }

  /** Deletes the team's copy through its kind's own delete, which refuses (409 in_use) while others use it. */
  async remove(copy: Obj): Promise<void> {
    const c = copyOf(copy);
    const [service, op, field] = DELETES[c.kind]!;
    await call(this.raw, service, op, { path: { [field]: c.record } });
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
