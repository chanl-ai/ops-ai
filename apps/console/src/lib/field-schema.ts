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
