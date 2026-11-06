import { z } from 'zod';

import { isRequired, type KindField } from './connect-plan.ts';

/**
 * The form schema for a list of fields as the API describes them (a sign-in kind's fields, a plugin's settings): every
 * value is text; a field is required as `isRequired` reads it, so a conditional field follows the other values typed;
 * PEM text must start as PEM does, and a field with choices takes one of them. One schema builder for every kind, so
 * every kind shows its errors the same way.
 */
export function schemaForFields(fields: KindField[]) {
  const shape = Object.fromEntries(fields.map((f) => [f.name, z.string()]));
  return z.object(shape).passthrough().superRefine((values, ctx) => {
    const settings = Object.fromEntries(Object.entries(values).map(([k, v]) => [k, typeof v === 'string' ? v : '']));
    for (const f of fields) {
      const value = (settings[f.name] ?? '').trim();
      if (!value) {
        if (isRequired(f, settings)) ctx.addIssue({ code: 'custom', path: [f.name], message: `Enter the ${f.label.charAt(0).toLowerCase()}${f.label.slice(1)}.` });
        continue;
      }
      if (f.pem && !value.startsWith('-----BEGIN')) ctx.addIssue({ code: 'custom', path: [f.name], message: 'Paste the PEM text, from its -----BEGIN line.' });
      if (f.choices?.length && !f.choices.includes(value)) ctx.addIssue({ code: 'custom', path: [f.name], message: `Pick one of: ${f.choices.join(', ')}.` });
    }
  });
}

/** The first error of each field a parse found, keyed by field name, for a form to show inline. */
export function fieldErrors(result: { success: boolean; error?: { issues: { path: PropertyKey[]; message: string }[] } }): Record<string, string> {
  if (result.success || !result.error) return {};
  const out: Record<string, string> = {};
  for (const issue of result.error.issues) {
    const name = String(issue.path[0] ?? '');
    if (name && !out[name]) out[name] = issue.message;
  }
  return out;
}

/**
 * An auth config field as the plugin declares it and the API describes it (GET /v1/app-credentials/{id} `fields`):
 * required or with a default, a choice among values, or a company's own address typed as a host under allowed suffixes.
 */
export interface ConfigField {
  name: string;
  label: string;
  required?: boolean;
  default?: string | null;
  choices?: { value: string | number | boolean; label: string }[] | null;
  other?: { label: string; value: string; hosts: string[] } | null;
  pem?: boolean;
}

/** The host a value holds when it is `other`'s address with a host in place of `{host}`; null when it is not. */
export function typedHost(other: ConfigField['other'], value: string): string | null {
  if (!other?.value.includes('{host}')) return null;
  const [head, tail] = other.value.split('{host}');
  return value.startsWith(head) && value.endsWith(tail) ? value.slice(head.length, value.length - tail.length) || null : null;
}

/**
 * The form schema of a plugin's auth config fields, built from the same declaration the API checks a saved value
 * against: a required field must be filled; a field with choices takes one of them or, when it allows one, a company's
 * address whose host ends in an allowed suffix. One builder for every plugin, so no form is written for one.
 */
export function configSchema(fields: ConfigField[]) {
  const shape = Object.fromEntries(fields.map((f) => [f.name, z.string()]));
  return z.object(shape).passthrough().superRefine((values, ctx) => {
    for (const f of fields) {
      const value = (typeof values[f.name] === 'string' ? (values[f.name] as string) : '').trim();
      const what = `${f.label.charAt(0).toLowerCase()}${f.label.slice(1)}`;
      if (!value) {
        if (f.required) ctx.addIssue({ code: 'custom', path: [f.name], message: `Enter ${what}.` });
        continue;
      }
      if (!f.choices?.length && !f.other) continue;
      if (f.choices?.some((c) => String(c.value) === value)) continue;
      const host = typedHost(f.other, value);
      if (host && f.other?.hosts.some((h) => host.endsWith(h) && host.length > h.length && !host.includes('/'))) continue;
      const places = [...(f.choices ?? []).map((c) => c.label), ...(f.other ? [`${f.other.label.toLowerCase()} ending in ${f.other.hosts.join(' or ')}`] : [])];
      ctx.addIssue({ code: 'custom', path: [f.name], message: `Choose ${places.length > 1 ? `${places.slice(0, -1).join(', ')} or ${places.at(-1)}` : places[0]}.` });
    }
  });
}
