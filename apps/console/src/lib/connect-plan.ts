/**
 * What the one connect dialog shows and does for an app's account, as data: its plan, the account's fields and draft,
 * and one reducer so a save, a test and a sign-in cannot overlap.
 *
 * The plan reads a kind's flags from `GET /v1/connection-kinds`, never its id, so a kind tools-service adds later (a
 * signed JWT, a private-key client) gets the right form with no change here. Only `none` is named: it has no fields.
 */

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
  /** PEM text, many lines long: a multi-line box and a file to read it from. */
  pem?: boolean;
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

export interface FieldGroups {
  /** The system's address and test path, then the kind's own fields, as a form shows them. */
  main: KindField[];
  /** Folded under More settings: advanced fields and the client certificate's. */
  more: KindField[];
}

/** An account's fields for a kind: the common ones, the kind's, and the certificate's under More settings. */
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

/** The account's draft in the dialog. A saved secret is only ever `secretSet`; its value is never read back. */
export interface Draft {
  settings: Record<string, string>;
  secrets: Record<string, string>;
  secretSet: Record<string, boolean>;
  status: SectionStatus;
  health?: Health | null;
}

/** A saved account as its detail answers it. */
export interface SavedAccount {
  settings: Record<string, unknown>;
  secrets: Record<string, { set?: boolean } | unknown>;
  health?: Health | null;
}

const text = (v: unknown): string => (v == null ? '' : typeof v === 'string' ? v : String(v));

/** The draft a dialog starts from: the saved values, else each field's default; typed secrets start empty. */
export function draftFor(groups: FieldGroups, saved?: SavedAccount | null): Draft {
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
  return { settings, secrets: {}, secretSet, status, health: saved?.health ?? null };
}

/** Whether a draft has what its required fields need: a value typed, or a secret already sealed. */
export function complete(draft: Draft, groups: FieldGroups): boolean {
  return [...groups.main, ...groups.more]
    .filter((f) => isRequired(f, draft.settings))
    .every((f) => (f.secret ? Boolean(draft.secrets[f.name]) || draft.secretSet[f.name] : Boolean(draft.settings[f.name]?.trim())));
}

/**
 * The keys `PATCH /v1/apps/{app_id}/accounts/{account_id}` takes for a draft: settings with blanks left out, and only
 * the secrets typed this time, so a sealed one left blank keeps its value.
 */
export function accountBody(draft: Draft, revision: number) {
  const settings = Object.fromEntries(Object.entries(draft.settings).filter(([, v]) => v.trim() !== ''));
  const secretValues = Object.fromEntries(Object.entries(draft.secrets).filter(([, v]) => v !== ''));
  return { revision, settings, secretValues };
}

export type Phase = 'form' | 'signing-in' | 'done';

export interface DialogState {
  phase: Phase;
  draft: Draft;
  /** The account the dialog made or opened; a new app has none until its first save. */
  connectionId: string | null;
  /** Whether this dialog made the account, so Cancel deletes it. */
  created: boolean;
  /** Whether a call is under way; every button that starts another waits. */
  busy: boolean;
  error: string | null;
  /** Whether the account holds keys, at its opening or by this dialog's save. */
  saved: boolean;
  /** Whether the account was signed in through this dialog, so Save does not open a second sign-in. */
  signedIn: boolean;
}

export type Action =
  | { type: 'reset'; draft: Draft; connectionId: string | null }
  | { type: 'setting'; name: string; value: string }
  | { type: 'secret'; name: string; value: string }
  /** `made`: this dialog made the account, so Cancel removes it; false when it opened one already there. */
  | { type: 'created'; connectionId: string; made?: boolean }
  | { type: 'start'; status: 'saving' | 'testing' }
  | { type: 'saved'; secretSet: Record<string, boolean> }
  | { type: 'tested'; health: Health | null }
  | { type: 'failed'; message: string }
  | { type: 'signing-in' }
  | { type: 'signed-in' }
  | { type: 'done' };

export const initialState = (draft: Draft, connectionId: string | null, saved = false): DialogState => ({
  phase: 'form',
  draft,
  connectionId,
  created: false,
  busy: false,
  error: null,
  saved,
  signedIn: false,
});

const edit = (s: DialogState, patch: Partial<Draft>): DialogState => ({ ...s, draft: { ...s.draft, ...patch } });

export function reduce(s: DialogState, a: Action): DialogState {
  switch (a.type) {
    case 'reset':
      return { ...initialState(a.draft, a.connectionId, s.saved), created: s.created };
    case 'setting':
      return edit(s, { settings: { ...s.draft.settings, [a.name]: a.value }, status: 'dirty' });
    case 'secret':
      return edit(s, { secrets: { ...s.draft.secrets, [a.name]: a.value }, status: 'dirty' });
    case 'created':
      return { ...s, connectionId: a.connectionId, created: a.made ?? true };
    case 'start':
      if (s.busy) return s;
      return { ...edit(s, { status: a.status }), busy: true, error: null };
    case 'saved':
      // A save is one step of a test or of Save: the dialog stays busy until that ends, so nothing starts beside it.
      return { ...edit(s, { secrets: {}, secretSet: { ...s.draft.secretSet, ...a.secretSet } }), saved: true };
    case 'tested':
      return { ...edit(s, { health: a.health, status: a.health?.status === 'ok' ? 'working' : 'failed' }), busy: false };
    case 'failed':
      return { ...edit(s, { status: 'dirty' }), busy: false, error: a.message };
    case 'signing-in':
      return { ...s, phase: 'signing-in', busy: false };
    case 'signed-in':
      return { ...s, phase: 'form', signedIn: true };
    case 'done':
      return { ...s, phase: 'done', busy: false, created: false };
  }
}

/**
 * The OAuth client a plugin's account signs in with: the id of one of the team's app credentials (made under
 * Credentials), `null` for Ops AI's app, or `undefined` to keep the one the account has (a later turn-on).
 */
export type Client = string | null | undefined;

/** What the connect dialog reads from a plugin's app card (`GET /v1/apps`). */
export interface PluginSpec {
  settings: { name: string; label: string; default?: string | null; secret: boolean; perAccount: boolean; locked: boolean }[];
  /** The kind's fields the plugin fixes itself. */
  fixed: string[];
  /** Whose account the plugin lets calls sign in with: team, person, person_or_team. */
  signIn?: string[];
}

/**
 * A plugin account's groups of fields. A kind that signs in asks only for the settings each account keeps its own (a
 * sandbox's sign-in address): its OAuth client is an app credential, picked, never typed here. Any other kind asks
 * for its own fields, which the plugin keeps as the account's credentials. The system's address and test address come
 * from the plugin, so they are never asked.
 */
export function pluginGroups(kind: Kind, kinds: Kinds, plugin: PluginSpec, saved = false): FieldGroups {
  // An account already set keeps its saved values, which it does not send back: its fields start blank and a blank
  // one is left out of the save, so saving without retyping never resets a value to its default.
  const perAccount: KindField[] = plugin.settings
    .filter((s) => s.perAccount && !s.locked)
    .map((s) =>
      saved
        ? { name: s.name, label: s.label, secret: s.secret, required: false, advanced: false, default: null, help: 'Blank keeps the saved value.' }
        : { name: s.name, label: s.label, secret: s.secret, required: !s.default, advanced: false, default: s.default },
    );
  if (kind.signsIn) return { main: perAccount, more: [] };
  // A field the plugin fixes (how its key is sent) is never asked: what a team typed would replace it. Nor is the
  // OAuth client of a kind that fetches a token with it: that is an app credential, picked.
  const asked = kind.fields.filter((f) => !plugin.fixed.includes(f.name) && !(kind.holdsToken && CLIENT_FIELDS.includes(f.name)));
  return { main: [...asked.filter((f) => !f.advanced), ...perAccount], more: [...asked.filter((f) => f.advanced), ...kinds.certificate] };
}

// The OAuth client's fields, an app credential's: never typed into an account.
const CLIENT_FIELDS = ['clientId', 'clientSecret'];

const filled = (o: Record<string, string>) => Object.fromEntries(Object.entries(o).filter(([, v]) => v.trim() !== ''));

/**
 * One plugin account's own keys from a draft: the settings it keeps its own, the app credential it signs in with when
 * one is picked (a kind that signs in or fetches a token), and for a kind that does not sign in the kind's fields as
 * credentials.
 */
export function pluginKeys(kind: Kind, plugin: PluginSpec, client: Client, draft: Draft): Record<string, unknown> {
  const own = new Set(plugin.settings.filter((s) => s.perAccount).map((s) => s.name));
  const keys: Record<string, unknown> = { settings: filled(Object.fromEntries(Object.entries(draft.settings).filter(([k]) => own.has(k)))) };
  if (!kind.signsIn) keys.credentials = filled({ ...Object.fromEntries(Object.entries(draft.settings).filter(([k]) => !own.has(k))), ...draft.secrets });
  if ((kind.signsIn || kind.holdsToken) && client !== undefined) keys.credentialId = client;
  return keys;
}

/** The `PUT /v1/apps/plugin:{id}/team` body that turns the plugin on with its default account's draft. */
export function turnOnBody(
  kind: Kind,
  plugin: PluginSpec,
  client: Client,
  draft: Draft,
  team: Record<string, string>,
  first: boolean,
  signIn?: string,
): Record<string, unknown> {
  const keys = pluginKeys(kind, plugin, client, draft);
  // The kind and whose account calls use are chosen at the first turn-on, when the team's default account is made.
  return {
    enabled: true,
    sandbox: false,
    ...keys,
    settings: { ...filled(team), ...(keys.settings as Record<string, string>) },
    ...(first ? { kind: kind.id, ...(signIn ? { signIn } : {}) } : {}),
  };
}

/** The `POST /v1/apps/plugin:{id}/accounts` body for another account of the plugin's app, a sandbox or a named one. */
export function newAccountBody(kind: Kind, plugin: PluginSpec, client: Client, draft: Draft, name: string, sandbox: boolean, signIn?: string): Record<string, unknown> {
  return { name, sandbox, kind: kind.id, ...(signIn ? { signIn } : {}), ...pluginKeys(kind, plugin, client, draft) };
}
