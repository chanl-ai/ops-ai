import type { DefinitionPublished, DefinitionPublishRequest, DefinitionValidation, DefinitionView, EngineDefinition, EngineNodeType, EngineOption, EngineRun, EngineRunDetail, EngineRunInput, EngineRunStarted, EngineRunsParams, OptionSource } from '@/lib/types/engine';
import type { ListResult } from '@/lib/types/query';

/** The workflow runner: node types, v2 definitions and runs. */
export interface EngineApi {
  /** Every registered node type at every version. */
  nodeTypes(): Promise<EngineNodeType[]>;
  /** The latest version, or `version`; 404 when the workflow has no v2 definition. */
  definition(workflowId: string, version?: number): Promise<DefinitionView>;
  /** The server's checks for a definition; saves nothing. */
  validate(definition: EngineDefinition): Promise<DefinitionValidation>;
  /** Saves it as the next version, a draft, once every check passes; 422 with the checks otherwise. */
  publish(definition: EngineDefinition): Promise<DefinitionPublished>;
  /** Opens a publish request for a draft in Reviews; 409 when one is open or the version is not a draft. */
  requestPublish(workflowId: string, input: { version?: number; note: string }): Promise<DefinitionPublishRequest>;
  /** Stops (true) or restarts live runs of the live version; 409 before a version is live. */
  setPaused(workflowId: string, paused: boolean): Promise<DefinitionView>;
  /** Choices for a node form field with an option source. */
  options(source: Exclude<OptionSource, 'steps'>): Promise<EngineOption[]>;
  /** Deletes every version of a workflow that has never run; 409 once it has runs, 404 when there is none. */
  deleteDefinition(workflowId: string): Promise<void>;
  /** Queues a run; a worker runs it. A live run starts only on the live version (409 otherwise); a test run on any. */
  startRun(input: EngineRunInput): Promise<EngineRunStarted>;
  /** The team's runs, newest first, a page at a time; `facets.status` counts each status under the other filters. */
  runs(params: EngineRunsParams): Promise<ListResult<EngineRun>>;
  run(runId: string): Promise<EngineRunDetail>;
  /** Cancels a run that has not ended; 409 once it succeeded or failed. */
  cancelRun(runId: string): Promise<EngineRun>;
}
