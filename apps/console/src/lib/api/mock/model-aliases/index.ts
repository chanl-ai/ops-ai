import type { AliasKnobs, ModelAliasRow } from '@/lib/types/models';

import { ApiError } from '../../contract';
import type { ModelAliasesApi } from '../../model-aliases-contract';
import { knobProblems } from '@/lib/model-forms';
import { list } from '../runtime';

// Sample aliases of a bank, an insurer and a plant: the connection ids are those of the mock's connections.
const SEED: ModelAliasRow[] = [
  { name: 'claude-haiku-4-5', version: 1, kind: 'chat', providerId: 'openai-local', modelId: 'gpt-4.1-mini', clearedSensitivity: 'confidential', inputPerMillion: '1', outputPerMillion: '5', status: 'current' },
  { name: 'claude-sonnet-5', version: 3, kind: 'chat', providerId: 'prov_claims', modelId: 'gpt-41-claims', clearedSensitivity: 'confidential', inputPerMillion: '3', outputPerMillion: '15', status: 'current' },
  { name: 'claude-opus-5-5', version: 1, kind: 'chat', providerId: 'openai-local', modelId: 'o4-mini', clearedSensitivity: 'restricted', inputPerMillion: '15', outputPerMillion: '75', status: 'current' },
  { name: 'claude-sonnet-5-preview', version: 1, kind: 'chat', providerId: 'prov_retail', modelId: 'gpt-4.1-mini', clearedSensitivity: 'internal', inputPerMillion: '0', outputPerMillion: '0', status: 'current' },
];

const NUM = (title: string, description: string, minimum: number | undefined, maximum: number | undefined, def: number) => ({ type: 'number' as const, title, description, minimum, maximum, default: def });
const INT = (title: string, description: string, minimum: number, def: number) => ({ type: 'integer' as const, title, description, minimum, default: def });
/** What each sample alias's model takes, as models-service's catalog would say; a reasoning model takes no temperature. */
const KNOBS: Record<string, AliasKnobs['knobs']['properties']> = {
  chat: {
    temperature: NUM('Temperature', 'Lower is steadier, higher is more varied.', 0, 2, 1),
    top_p: NUM('Top p', 'Only the most likely words whose chances add up to this are considered.', 0, 1, 1),
    max_tokens: INT('Longest answer (tokens)', 'The most tokens one answer may use, thinking included.', 1, 16384),
  },
  reasoning: {
    max_tokens: INT('Longest answer (tokens)', 'The most tokens one answer may use, thinking included.', 1, 16384),
    reasoning_effort: { type: 'string', title: 'Thinking effort', description: 'How hard the model thinks. Higher is slower and costs more per answer.', enum: ['low', 'medium', 'high'], default: 'medium' },
  },
};

/** The sample knobs of an alias name; one that is not served is refused as agents-service refuses it. */
export function mockKnobs(rows: ModelAliasRow[], name: string): AliasKnobs {
  const row = rows.find((r) => r.name === name);
  if (!row) throw new ApiError(`No model alias ${name}.`, 422, undefined, 'unknown_model_alias');
  return { alias: name, version: row.version, modelId: row.modelId, catalogued: true, knobs: { type: 'object', properties: row.modelId.startsWith('o') ? KNOBS.reasoning : KNOBS.chat } };
}

/** As agents-service answers a save: the first setting the alias's model does not take, or takes out of range (422 `model_setting_invalid`). */
export function mockSettingProblem(rows: ModelAliasRow[], alias: string, settings: Record<string, number | string>): void {
  const knobs = mockKnobs(rows, alias).knobs.properties;
  const unknown = Object.keys(settings).find((k) => !(k in knobs));
  const range = Object.entries(knobProblems(knobs, settings))[0];
  const bad = unknown ? [unknown, 'is not a setting this model takes'] : range;
  if (bad) throw new ApiError(`${bad[0]}: ${bad[1]}`, 422, undefined, 'model_setting_invalid', { alias });
}

/** Sample aliases for a console with no models-service; nothing outlives a reload. */
export function createMockModelAliases(): ModelAliasesApi & { rows: () => ModelAliasRow[] } {
  let rows = structuredClone(SEED);
  return {
    rows: () => rows,
    list: async (p) => list(rows, p, { text: (a) => `${a.name} ${a.modelId}`, value: () => '', facetKeys: [], id: (a) => a.name }, 'normal'),
    create: async (input) => {
      if (rows.some((r) => r.name === input.name)) throw new ApiError(`An alias named ${input.name} exists.`, 409, undefined, 'alias_exists');
      rows = [...rows, { name: input.name, version: 1, kind: 'chat', providerId: input.providerId, modelId: input.modelId, clearedSensitivity: input.clearedSensitivity, inputPerMillion: String(input.inputPerMillion ?? 0), outputPerMillion: String(input.outputPerMillion ?? 0), status: 'current' }].sort((a, b) => a.name.localeCompare(b.name));
      return { name: input.name, version: 1 };
    },
    newVersion: async (name, input) => {
      const was = rows.find((r) => r.name === name);
      if (!was) throw new ApiError(`No alias ${name}.`, 404, undefined, 'alias_not_found');
      const version = was.version + 1;
      rows = rows.map((r) => (r.name === name ? { ...r, version, providerId: input.providerId, modelId: input.modelId, clearedSensitivity: input.clearedSensitivity, inputPerMillion: String(input.inputPerMillion ?? 0), outputPerMillion: String(input.outputPerMillion ?? 0) } : r));
      return { name, version };
    },
  };
}
