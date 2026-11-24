/**
 * Workflow authoring and runs over the generated agents operations.
 * YAML files are a Python/CLI concern; this surface accepts a parsed object or JSON text.
 */
import { NotFound } from './errors.js';
import { based } from './agents.js';
import { eachPage } from './transport.js';

export const PLANNED = 'This command is planned; the public API for it is not shipped.';

export type DefinitionSource = Record<string, unknown> | string;

function asDefinition(source: DefinitionSource): Record<string, unknown> {
  if (typeof source === 'string') return JSON.parse(source) as Record<string, unknown>;
  return source;
}

function body(source: DefinitionSource): { definition: Record<string, unknown> } {
  return { definition: asDefinition(source) };
}

export class WorkflowCheck {
  constructor(readonly data: Record<string, any>) {}
  get ok(): boolean {
    return Boolean(this.data.ok);
  }
  get checks(): Record<string, any>[] {
    return (this.data.checks as Record<string, any>[]) ?? [];
  }
  get errors(): Record<string, any>[] {
    return this.checks.filter((c) => c.level !== 'warning');
  }
  raiseForErrors(): void {
    if (this.ok) return;
    const first = this.errors[0] ?? { code: 'invalid', message: 'the definition failed checks' };
    throw new Error(`${first.path ?? first.node ?? first.code}: ${first.message}`);
  }
}

export class Workflows {
  constructor(
    private readonly raw: { agents: any },
    private readonly runs: { start: Function; wait: Function },
  ) {}

  /** Every workflow definition, page after page (`search`, `ids`, `status`). */
  list(query: Record<string, unknown> = {}) {
    return eachPage((page) => this.raw.agents.workflows_list_definitions({ query: page }), query);
  }

  /** The workflow's forms, every page (`search`, `ids`). */
  forms(workflowId: string, query: Record<string, unknown> = {}) {
    return eachPage((page) => this.raw.agents.forms_workflow_forms({ path: { workflow_id: workflowId }, query: page }), query);
  }

  /** Starts a batch over the rows of an uploaded file. The API refuses a field it does not name. */
  startBatch(workflowId: string, fileId: string, options: { mode?: 'live' | 'test'; dryRun?: boolean } = {}) {
    const { mode, dryRun } = options;
    const body = { fileId, ...(mode === undefined ? {} : { mode }), ...(dryRun === undefined ? {} : { dryRun }) };
    return this.raw.agents.batches_start_batch({ path: { workflow_id: workflowId }, body: body as never });
  }

  /** The workflow's batches, uploads and checks of a watched folder, newest first, every page (`sortOrder`). */
  batches(workflowId: string, query: Record<string, unknown> = {}) {
    return eachPage((page) => this.raw.agents.batches_list_batches({ path: { workflow_id: workflowId }, query: page }), query);
  }

  /** One batch with its counts and every row, failed first. */
  getBatch(batchId: string) {
    return this.raw.agents.batches_batch_page({ path: { batch_id: batchId } });
  }

  async types(group?: string) {
    const found = (await this.raw.agents.workflows_node_types()) as Record<string, any>[];
    return group ? found.filter((t) => t.group === group) : found;
  }

  async type(id: string) {
    const found = (await this.types()).find((t) => t.id === id);
    if (!found) throw new NotFound(404, 'not_found', `node type ${id}`);
    return found;
  }

  async validate(definition: DefinitionSource) {
    return new WorkflowCheck(
      (await this.raw.agents.workflows_validate_definition({ body: body(definition) as never })) as Record<string, any>,
    );
  }

  async apply(definition: DefinitionSource) {
    return this.raw.agents.workflows_create_definition({ body: body(definition) as never });
  }

  getDefinition(id: string, version?: number) {
    return this.raw.agents.workflows_get_definition({ path: { workflow_id: id }, query: { version } });
  }

  async export(id: string, format: 'json' | 'yaml' = 'json') {
    const view = (await this.getDefinition(id)) as { definition: Record<string, unknown> };
    if (format === 'yaml') throw new Error('YAML export is available on the Python SDK and CLI');
    return JSON.stringify(view.definition, null, 2);
  }

  /**
   * Saves `definition` as the workflow's working copy, failing checks and all; it makes no version. `base` is the
   * `saveBase` of the workflow as last read; left out, the workflow is read first. A save made on an older copy is
   * refused with `stale_base`.
   */
  async saveWorkingCopy(id: string, definition: DefinitionSource, base?: { version: number; digest: string }) {
    const read = base ?? ((await this.getDefinition(id)) as { saveBase: { version: number; digest: string } }).saveBase;
    return this.raw.agents.workflows_save_working_copy({ path: { workflow_id: id }, body: based(body(definition), read) as never });
  }

  /** The steps added, removed, changed and moved between two versions, `live` or `working-copy`. */
  diff(id: string, from: string | number = 'live', to: string | number = 'working-copy') {
    return this.raw.agents.workflows_diff_definitions({ path: { workflow_id: id }, query: { from: String(from), to: String(to) } });
  }

  /** What publishing the working copy would change, what stops it, and whether it waits for a review. */
  publishPreview(id: string) {
    return this.raw.agents.workflows_publish_preview({ path: { workflow_id: id } });
  }

  /**
   * Requests the publish of the newest draft or, with `workingCopy`, makes the next version from the working copy and
   * requests its publish in one call, refused before any version is made while the publish preview lists a blocker.
   */
  async publish(id: string, note = '', workingCopy = false) {
    const read = workingCopy ? ((await this.getDefinition(id)) as { saveBase: { version: number; digest: string } }).saveBase : null;
    return this.raw.agents.workflows_request_definition_publish({
      path: { workflow_id: id },
      body: (read ? based({ note }, read) : { note }) as never,
    });
  }

  pause(id: string) {
    return this.raw.agents.workflows_pause_definition({ path: { workflow_id: id } });
  }

  archive(id: string) {
    return this.raw.agents.workflows_archive_definition({ path: { workflow_id: id } });
  }

  async run(
    id: string,
    options: { input?: Record<string, unknown>; mode?: string; wait?: boolean; [field: string]: unknown } = {},
  ) {
    const { input, wait, mode = 'test', ...fields } = options;
    const started = await this.runs.start(id, { input: input ?? {}, mode, ...fields });
    return wait ? this.runs.wait((started as { runId: string }).runId) : started;
  }

  sendTestEmail(id: string, values: Record<string, unknown>, mode = 'test') {
    return this.raw.agents.workflows_start_by_hand({
      body: { workflowId: id, mode, values } as never,
    });
  }

  async trace(runId: string) {
    const run = (await this.raw.agents.workflows_get_engine_run({ path: { run_id: runId } })) as Record<string, any>;
    return { run, steps: run.steps ?? [], failure: run.failure, story: run.story };
  }

  replay(_runId: string): never {
    throw new Error(PLANNED);
  }

  fork(_runId: string, _fromNode: string): never {
    throw new Error(PLANNED);
  }
}
