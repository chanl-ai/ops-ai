/**
 * Workflow authoring and runs over the generated agents operations.
 * YAML files are a Python/CLI concern; this surface accepts a parsed object or JSON text.
 */
import { NotFound } from './errors.js';

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

  publish(id: string, note = '') {
    return this.raw.agents.workflows_request_definition_publish({
      path: { workflow_id: id },
      body: { note } as never,
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
