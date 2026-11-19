/**
 * `ops.templates`: what a team can start from (agents, skills, workflows, guardrails, case types, task types and
 * document types from the packs and apps that are on for the team), and installing one as the team's own copy.
 *
 * A template is named `<source>:<id>`, for example `plugin:opsai.starters:doc-coauthoring`. Document types are kept
 * by documents-service and every other kind by agents-service, so a list without a kind reads both.
 */
import type { Raw } from './client.js';

// biome-ignore lint/suspicious/noExplicitAny: a template row is read as the service answers it
type Obj = Record<string, any>;

const DOCUMENT_TYPE = 'document_type';

// biome-ignore lint/suspicious/noExplicitAny: the generated operations are typed per id; these words pass them through
const call = (raw: Raw, service: 'agents' | 'documents', id: string, args: Obj = {}): Promise<any> =>
  (raw[service] as unknown as Record<string, (a: Obj) => Promise<unknown>>)[id]!(args);

const refOf = (t: Obj | string) => (typeof t === 'string' ? t : `${t.source}:${t.id}`);

export class Templates {
  constructor(private readonly raw: Raw) {}

  /** Every template offered to the team, each with its state, the team's copies and `canAdd`; `kind` keeps one kind,
   * `source` one pack or app (`plugin:<id>`). */
  async list({ kind, source }: { kind?: string; source?: string } = {}): Promise<Obj[]> {
    const out: Obj[] = [];
    if (kind !== DOCUMENT_TYPE) out.push(...(await call(this.raw, 'agents', 'templates_list_templates', { query: { kind, source } })));
    if (kind === undefined || kind === DOCUMENT_TYPE) {
      const docs: Obj[] = await call(this.raw, 'documents', 'templates_list_templates', { query: { kind } });
      out.push(...docs.filter((t) => source === undefined || t.source === source));
    }
    return out;
  }

  /** Adds the template to the team as its own copy, through the same checks as creating one of its kind by hand. */
  async install(template: Obj | string, { kind, ...fields }: { kind?: string; [field: string]: unknown } = {}): Promise<Obj> {
    const ref = refOf(template);
    let k = kind ?? (typeof template === 'string' ? undefined : template.kind);
    if (k === undefined) {
      // agents-service keeps every kind but document types, so it is asked first.
      const mine: Obj[] = await call(this.raw, 'agents', 'templates_list_templates', { query: { source: ref.slice(0, ref.lastIndexOf(':')) } });
      k = mine.find((t) => refOf(t) === ref)?.kind ?? DOCUMENT_TYPE;
    }
    return call(this.raw, k === DOCUMENT_TYPE ? 'documents' : 'agents', 'resources_copy_resource', { path: { resource: ref }, body: fields });
  }
}
