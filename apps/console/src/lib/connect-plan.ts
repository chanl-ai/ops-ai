/**
 * What the one connect dialog shows and does for a system (c-580), as data: its plan, each environment's fields and
 * draft, and one reducer so a save, a test and a sign-in cannot overlap.
 *
 * The plan reads a kind's flags from `GET /v1/connection-kinds`, never its id, so a kind tools-service adds later (a
 * signed JWT, a private-key client) gets the right form with no change here. Only `none` is named: it has no fields.
 */

/** An environment's id, as `GET /v1/connection-kinds` lists them; never a fixed set, so teams may name their own. */
export type Environment = string;

export interface EnvironmentOption {
  id: Environment;
  label: string;
  /** The one environment live runs call. */
  production: boolean;
}

/** A field as `GET /v1/connection-kinds` describes it. */
export interface KindField {
  name: string;
  label: string;
  secret: boolean;
  required: boolean;
  advanced: boolean;
  choices?: string[] | null;
  default?: string | null;
  help?: string | null;
  /** Required once every named setting holds its value. */
  requiredWhen?: Record<string, string> | null;
  /** Not required once every named setting holds its value, unless `requiredWhen` matches. */
  optionalWhen?: Record<string, string> | null;
}

const matches = (when: Record<string, string> | null | undefined, settings: Record<string, string>) =>
  Boolean(when && Object.keys(when).length) && Object.entries(when ?? {}).every(([k, v]) => settings[k] === v);

/** Whether a field is required with these settings, read as tools-service reads it (`Kind.requires`). */
export function isRequired(field: KindField, settings: Record<string, string>): boolean {
  if (matches(field.requiredWhen, settings)) return true;
  if (matches(field.optionalWhen, settings)) return false;
  return field.required;
}

/** A sign-in kind as `GET /v1/connection-kinds` describes it. */
export interface Kind {
  id: string;
  label: string;
  fields: KindField[];
  /** Someone signs in once in the browser before calls can use it. */
  signsIn: boolean;
  /** The connection holds a token the gateway fetches and refreshes, so Reconnect applies. */
  holdsToken: boolean;
  /** Each person may connect their own account, whatever way the kind signs in. */
  perPerson: boolean;
}

export interface Kinds {
  kinds: Kind[];
  environments: EnvironmentOption[];
  common: KindField[];
  certificate: KindField[];
  redirectUri?: string | null;
}

export type Plan = { kind: 'none'; authKind: Kind } | { kind: 'keys'; authKind: Kind } | { kind: 'account'; authKind: Kind };

/** The plan for a sign-in kind: no fields, keys to enter and test, or keys and then someone signs in. */
export function planFor(kind: Kind): Plan {
  if (kind.id === 'none') return { kind: 'none', authKind: kind };
  return kind.signsIn ? { kind: 'account', authKind: kind } : { kind: 'keys', authKind: kind };
}

/** The environments in the order a dialog shows them: the one asked for first, then the service's order. */
export function ordered(kinds: Kinds, first?: Environment): EnvironmentOption[] {
  const all = kinds.environments;
  const lead = all.find((e) => e.id === first);
  return lead ? [lead, ...all.filter((e) => e !== lead)] : all;
}

/** The environment a sign-in or Save starts from: production when it is among `ids`, else the first of them. */
export function leading(kinds: Kinds, ids: Environment[]): Environment | undefined {
  return kinds.environments.find((e) => e.production && ids.includes(e.id))?.id ?? kinds.environments.find((e) => ids.includes(e.id))?.id;
}

export interface FieldGroups {
  /** The system's address and test path, then the kind's own fields, as a form shows them. */
  main: KindField[];
  /** Folded under More settings: advanced fields and the client certificate's. */
  more: KindField[];
}

/** One environment's fields for a kind: the common ones, the kind's, and the certificate's under More settings. */
export function fieldsFor(kind: Kind, kinds: Kinds): FieldGroups {
  const all = [...kinds.common, ...kind.fields];
  return {
    main: all.filter((f) => !f.advanced),
    more: [...all.filter((f) => f.advanced), ...kinds.certificate],
  };
}

export type SectionStatus = 'empty' | 'dirty' | 'saving' | 'testing' | 'working' | 'failed';

export interface Health {
  status: string;
  httpStatus?: number | null;
  code?: string | null;
  message?: string | null;
  latencyMs?: number | null;
  at: string;
}

/** One environment's section of the dialog. A saved secret is only ever `secretSet`; its value is never read back. */
export interface EnvDraft {
  environment: Environment;
  settings: Record<string, string>;
  secrets: Record<string, string>;
  secretSet: Record<string, boolean>;
  status: SectionStatus;
  health?: Health | null;
}

/** A saved environment as a connection's detail answers it. */
export interface SavedEnvironment {
  set: boolean;
  settings: Record<string, unknown>;
  secrets: Record<string, { set?: boolean } | unknown>;
  health?: Health | null;
}

const text = (v: unknown): string => (v == null ? '' : typeof v === 'string' ? v : String(v));

/** A section's starting draft: the saved values, else each field's default; typed secrets start empty. */
export function draftFor(environment: Environment, groups: FieldGroups, saved?: SavedEnvironment | null): EnvDraft {
  const settings: Record<string, string> = {};
  const secretSet: Record<string, boolean> = {};
  for (const f of [...groups.main, ...groups.more]) {
    if (f.secret) {
      const s = saved?.secrets?.[f.name];
      secretSet[f.name] = Boolean(s && typeof s === 'object' && (s as { set?: boolean }).set);
    } else {
      const v = saved?.settings?.[f.name];
      settings[f.name] = v != null && v !== '' ? text(v) : (f.default ?? '');
    }
  }
  const status: SectionStatus = saved?.health ? (saved.health.status === 'ok' ? 'working' : 'failed') : 'empty';
  return { environment, settings, secrets: {}, secretSet, status, health: saved?.health ?? null };
}

/** Whether a section has what its required fields need: a value typed, or a secret already sealed. */
export function complete(draft: EnvDraft, groups: FieldGroups): boolean {
  return [...groups.main, ...groups.more]
    .filter((f) => isRequired(f, draft.settings))
    .every((f) => (f.secret ? Boolean(draft.secrets[f.name]) || draft.secretSet[f.name] : Boolean(draft.settings[f.name]?.trim())));
}

/**
 * The body `PUT /v1/connections/{id}/environments/{env}` takes for a section: settings with blanks left out, and only
 * the secrets typed this time, so a sealed one left blank keeps its value.
 */
export function environmentBody(draft: EnvDraft, revision: number) {
  const settings = Object.fromEntries(Object.entries(draft.settings).filter(([, v]) => v.trim() !== ''));
  const secretValues = Object.fromEntries(Object.entries(draft.secrets).filter(([, v]) => v !== ''));
  return { revision, settings, secretValues };
}

export type Phase = 'form' | 'signing-in' | 'done';

export interface DialogState {
  phase: Phase;
  sections: Record<Environment, EnvDraft>;
  /** The connection the dialog made or opened; a new system has none until its first save. */
  connectionId: string | null;
  /** Whether this dialog made the connection, so Cancel deletes it. */
  created: boolean;
  /** Whether a call is under way; every button that starts another waits. */
  busy: boolean;
  error: string | null;
}

export type Action =
  | { type: 'reset'; sections: Record<Environment, EnvDraft>; connectionId: string | null }
  | { type: 'setting'; environment: Environment; name: string; value: string }
  | { type: 'secret'; environment: Environment; name: string; value: string }
  /** `made`: this dialog made the connection, so Cancel removes it; false when it opened one already there. */
  | { type: 'created'; connectionId: string; made?: boolean }
  | { type: 'start'; environment: Environment; status: 'saving' | 'testing' }
  | { type: 'saved'; environment: Environment; secretSet: Record<string, boolean> }
  | { type: 'tested'; environment: Environment; health: Health | null }
  | { type: 'failed'; environment?: Environment; message: string }
  | { type: 'signing-in' }
  | { type: 'signed-in' }
  | { type: 'done' };

export const initialState = (sections: Record<Environment, EnvDraft>, connectionId: string | null): DialogState => ({
  phase: 'form',
  sections,
  connectionId,
  created: false,
  busy: false,
  error: null,
});

const edit = (s: DialogState, env: Environment, patch: Partial<EnvDraft>): DialogState => ({
  ...s,
  sections: { ...s.sections, [env]: { ...s.sections[env], ...patch } },
});

export function reduce(s: DialogState, a: Action): DialogState {
  switch (a.type) {
    case 'reset':
      return initialState(a.sections, a.connectionId);
    case 'setting':
      return edit(s, a.environment, { settings: { ...s.sections[a.environment].settings, [a.name]: a.value }, status: 'dirty' });
    case 'secret':
      return edit(s, a.environment, { secrets: { ...s.sections[a.environment].secrets, [a.name]: a.value }, status: 'dirty' });
    case 'created':
      return { ...s, connectionId: a.connectionId, created: a.made ?? true };
    case 'start':
      if (s.busy) return s;
      return { ...edit(s, a.environment, { status: a.status }), busy: true, error: null };
    case 'saved': {
      // A save is one step of a test or of Save: the dialog stays busy until that ends, so nothing starts beside it.
      const sec = s.sections[a.environment];
      return edit(s, a.environment, { secrets: {}, secretSet: { ...sec.secretSet, ...a.secretSet } });
    }
    case 'tested':
      return { ...edit(s, a.environment, { health: a.health, status: a.health?.status === 'ok' ? 'working' : 'failed' }), busy: false };
    case 'failed':
      return { ...(a.environment ? edit(s, a.environment, { status: 'dirty' }) : s), busy: false, error: a.message };
    case 'signing-in':
      return { ...s, phase: 'signing-in', busy: false };
    case 'signed-in':
      return { ...s, phase: 'form' };
    case 'done':
      return { ...s, phase: 'done', busy: false, created: false };
  }
}

/** Which app a plugin that signs in uses: the platform's, set up once by an account admin, or the team's own. */
export type App = 'platform' | 'own';

/** What the connect dialog reads from a plugin's system card (`GET /v1/systems`). */
export interface PluginSpec {
  settings: { name: string; label: string; default?: string | null; secret: boolean; perEnvironment: boolean; locked: boolean }[];
  /** The kind's fields the plugin fixes itself. */
  fixed: string[];
}

const CLIENT_ID: KindField = { name: 'clientId', label: 'Client ID', secret: false, required: true, advanced: false };
const CLIENT_SECRET: KindField = { name: 'clientSecret', label: 'Client secret', secret: true, required: true, advanced: false };

/**
 * A plugin's groups of fields per environment. A kind that signs in asks for the team's own app (client ID and secret)
 * unless the platform's app is chosen, plus the settings each environment keeps its own (a sandbox's sign-in address);
 * any other kind asks for its own fields, which the plugin keeps as the connection's credentials. The system's address
 * and test address come from the plugin, so they are never asked.
 */
export function pluginGroups(kind: Kind, kinds: Kinds, plugin: PluginSpec, app: App): FieldGroups {
  const perEnv: KindField[] = plugin.settings
    .filter((s) => s.perEnvironment && !s.locked)
    .map((s) => ({ name: s.name, label: s.label, secret: s.secret, required: !s.default, advanced: false, default: s.default }));
  if (kind.signsIn) return { main: [...(app === 'own' ? [CLIENT_ID, CLIENT_SECRET] : []), ...perEnv], more: [] };
  // A field the plugin fixes (how its key is sent) is never asked: what a team typed would replace it.
  const asked = kind.fields.filter((f) => !plugin.fixed.includes(f.name));
  return { main: [...asked.filter((f) => !f.advanced), ...perEnv], more: [...asked.filter((f) => f.advanced), ...kinds.certificate] };
}

/** The `PUT /v1/plugins/{id}/team` body that turns the plugin on for one environment with that section's values. */
export function turnOnBody(kind: Kind, plugin: PluginSpec, app: App, draft: EnvDraft, team: Record<string, string>, first: boolean): Record<string, unknown> {
  const own = new Set(plugin.settings.filter((s) => s.perEnvironment).map((s) => s.name));
  const filled = (o: Record<string, string>) => Object.fromEntries(Object.entries(o).filter(([, v]) => v.trim() !== ''));
  const settings = filled({ ...team, ...Object.fromEntries(Object.entries(draft.settings).filter(([k]) => own.has(k))) });
  const body: Record<string, unknown> = { enabled: true, environment: draft.environment, settings, ...(first ? { kind: kind.id } : {}) };
  if (kind.signsIn) {
    if (app === 'own')
      Object.assign(body, { clientId: draft.settings.clientId, ...(draft.secrets.clientSecret ? { clientSecret: draft.secrets.clientSecret } : {}) });
  } else {
    const credentials = filled({ ...Object.fromEntries(Object.entries(draft.settings).filter(([k]) => !own.has(k))), ...draft.secrets });
    body.credentials = credentials;
  }
  return body;
}
