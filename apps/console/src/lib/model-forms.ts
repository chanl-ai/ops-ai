import { nameError } from './validation/names.ts';
import type { AliasKnobs, ConnectionSchemaField, KnobSchema, ProviderConnectionInput, ProviderTypeInfo } from './types/models.ts';

/** The connection column each `x-column` names, as the create route spells it. */
const COLUMN = { base_url: 'baseUrl', api_version: 'apiVersion', region: 'region' } as const;

/** The name a connection's key is saved under: its own name in capitals, so one connection never shares another's key. */
export function keyRefFor(name: string): string {
  const ref = name
    .trim()
    .toUpperCase()
    .replace(/[^A-Z0-9_.-]+/g, '_')
    .replace(/^[^A-Z0-9]+/, '')
    .slice(0, 120);
  return ref;
}

/** The values a type's form starts with: each field's schema default. */
export function connectionDefaults(type: ProviderTypeInfo): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [name, field] of Object.entries(type.connection.properties ?? {})) if (field.default !== undefined) out[name] = field.default;
  return out;
}

const text = (v: unknown) => (typeof v === 'string' ? v.trim() : '');

/** What each field the form leaves empty or invalid says, by property name. */
export function connectionProblems(type: ProviderTypeInfo, name: string, values: Record<string, unknown>): Record<string, string> {
  const out: Record<string, string> = {};
  const named = nameError(name, 'Name the connection.');
  if (named) out.name = named;
  const fields = type.connection.properties ?? {};
  for (const required of type.connection.required ?? []) {
    const label = fields[required]?.title ?? required;
    if (!text(values[required])) out[required] = `Enter the ${label.charAt(0).toLowerCase()}${label.slice(1)}.`;
  }
  for (const [prop, field] of Object.entries(fields)) {
    if (field.format === 'uri' && text(values[prop]) && !/^https?:\/\/[^\s/]+/.test(text(values[prop]))) out[prop] ??= 'Enter an address starting with https://.';
  }
  return out;
}

/**
 * The create request for a form of `type`: a field with an `x-column` goes in its column, an `x-secret` field goes
 * only in `secrets` and is never a column, and a connection given no secret sends neither `secrets` nor a `keyRef`.
 */
export function connectionBody(type: ProviderTypeInfo, name: string, values: Record<string, unknown>): ProviderConnectionInput {
  const body: ProviderConnectionInput = { name: name.trim(), type: type.id };
  const secrets: Record<string, string> = {};
  for (const [prop, field] of Object.entries(type.connection.properties ?? {}) as [string, ConnectionSchemaField][]) {
    const value = text(values[prop]);
    if (!value) continue;
    if (field['x-secret']) secrets[prop] = value;
    else if (field['x-column']) body[COLUMN[field['x-column']]] = value;
  }
  if (Object.keys(secrets).length) {
    body.secrets = secrets;
    body.keyRef = keyRefFor(name);
  }
  return body;
}

/** Where a saved connection's key is tested and its models listed (the key check's own request body). */
export function keyWhere(type: string, body: ProviderConnectionInput) {
  return { provider: type, ...(body.baseUrl ? { endpoint: body.baseUrl } : {}), ...(body.apiVersion ? { apiVersion: body.apiVersion } : {}), ...(body.region ? { region: body.region } : {}) };
}

/** Each number an agent set that its model's range refuses, by knob; models-service refuses the same on save. */
export function knobProblems(knobs: Record<string, KnobSchema>, settings: Record<string, number | string>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [name, value] of Object.entries(settings)) {
    const knob = knobs[name];
    if (!knob || typeof value !== 'number') continue;
    if (knob.minimum !== undefined && value < knob.minimum) out[name] = `At least ${knob.minimum}.`;
    else if (knob.maximum !== undefined && value > knob.maximum) out[name] = `At most ${knob.maximum}.`;
    else if (knob.type === 'integer' && !Number.isInteger(value)) out[name] = 'A whole number.';
  }
  return out;
}

/**
 * The settings an agent keeps when it moves to an alias: only those the new alias's model takes, so none is saved that
 * the service would refuse (422 `model_setting_invalid`).
 */
export function settingsForAlias(next: AliasKnobs['knobs']['properties'], current: Record<string, number | string>): Record<string, number | string> {
  return Object.fromEntries(Object.entries(current).filter(([name]) => name in next));
}

/** What an alias may be cleared for, least to most sensitive (models-service's `clearedSensitivity`). */
export const SENSITIVITIES = ['public', 'internal', 'confidential', 'restricted'] as const;

/** The rule models-service holds an alias name to. */
export function aliasNameProblem(name: string): string | undefined {
  return /^[a-z0-9][a-z0-9.-]{1,118}$/.test(name.trim()) ? undefined : 'Use lowercase letters, digits, dots and dashes, at least two characters.';
}

/** A price the person typed: empty leaves it to the catalog (the dialog sends no price when both are empty), anything else a number of at least 0. */
/** Where a refused alias save shows: by the error's code, since a message names the alias, and an alias may be called
 * "price-bot" or "named-x". A taken name goes on the name field of a new alias; a price refusal on the price field. */
export function aliasSaveErrors(e: { message: string; code?: string }, editing: boolean): { name?: string; inputPerMillion?: string; submit?: string } {
  if (e.code === 'alias_exists' && !editing) return { name: e.message };
  if (e.code === 'price_required' || e.code === 'price_incomplete') return { inputPerMillion: e.message };
  return { submit: e.message };
}

export function priceProblem(value: string): string | undefined {
  if (!value.trim()) return undefined;
  const n = Number(value);
  return Number.isFinite(n) && n >= 0 ? undefined : 'Enter a price of 0 or more.';
}

/** Who may change aliases: they apply to every team in the install, so models-service asks for install.manage. */
export const ALIAS_READ_ONLY_REASON = 'Only the workspace owner changes model aliases, because they apply to every team in the install.';
export function aliasWriteAccess(canManageInstall: boolean | undefined): { editable: boolean; reason: string | null } {
  return canManageInstall === true ? { editable: true, reason: null } : { editable: false, reason: canManageInstall === undefined ? null : ALIAS_READ_ONLY_REASON };
}

/** The Used by cell: a count of agents, or a dash when the service does not know (never 0, which would claim it is free to remove). */
export function usedByLabel(usedBy: number | null | undefined): string {
  return typeof usedBy === 'number' ? `${usedBy} ${usedBy === 1 ? 'agent' : 'agents'}` : '–';
}
