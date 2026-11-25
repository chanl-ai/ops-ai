import type { DefinitionDiff, DefinitionPublished, DefinitionPublishRequest, DefinitionValidation, DefinitionView, DiffSide, WorkflowPublishPreview, WorkingCopySaved, EngineDefinition, EngineNodeType, EngineOption, EngineRun, EngineRunDetail, EngineRunInput, EngineRunStarted, EngineRunsParams, OptionSource, StartWorkflowInput } from '@/lib/types/engine';
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
  /** Saves the editor's working copy, failing checks and all; makes no version. 409 `stale_base` when `base` is not the newest copy. */
  saveWorkingCopy(workflowId: string, definition: EngineDefinition, base: { baseVersion: number; baseDigest: string; replacesDigest?: string }): Promise<WorkingCopySaved>;
  /** What changed between two versions, the live one or the working copy. */
  diff(workflowId: string, from: DiffSide, to: DiffSide): Promise<DefinitionDiff>;
  /** What a publish of the working copy would change, what stops it, and whether it waits for a review. */
  publishPreview(workflowId: string): Promise<WorkflowPublishPreview>;
  /** Opens a publish request for a draft in Reviews; 409 when one is open or the version is not a draft. */
  /** Opens a draft's publish request; with `baseVersion`/`baseDigest` it publishes the working copy in one call, refused before any version is made while a blocker remains. */
  requestPublish(workflowId: string, input: { version?: number; note: string; baseVersion?: number; baseDigest?: string }): Promise<DefinitionPublishRequest>;
  /** Stops (true) or restarts live runs of the live version; 409 before a version is live. */
  setPaused(workflowId: string, paused: boolean): Promise<DefinitionView>;
  /** Choices for a node form field with an option source. */
  options(source: Exclude<OptionSource, 'steps'>): Promise<EngineOption[]>;
  /** Deletes every version of a workflow that has never run; 409 once it has runs, 404 when there is none. */
  deleteDefinition(workflowId: string): Promise<void>;
  /** Queues a run; a worker runs it. A live run starts only on the live version (409 otherwise); a test run on any. */
  startRun(input: EngineRunInput): Promise<EngineRunStarted>;
  /** Starts a run from the start form its trigger declares, through the entry the real source uses; 422 for a trigger with none. */
  startWorkflow(input: StartWorkflowInput): Promise<EngineRunStarted>;
  run(runId: string): Promise<EngineRunDetail>;
  /** Cancels a run that has not ended; 409 once it succeeded or failed. */
  cancelRun(runId: string): Promise<EngineRun>;
  /** Queues a Stuck run again from its last recorded step; 409 `run_not_stuck` once it moved on. */
  retryRun(runId: string): Promise<EngineRun>;
  /** Queues a Failed or Stuck run again from its failed step, on its own version; 409 `run_not_redrivable` otherwise. */
  redriveRun(runId: string): Promise<EngineRun>;
  /** Starts the run of an email the mailbox listener set aside, under the email's own run key; 404 once it ran. */
  runSetAsideEmail(eventId: string): Promise<EngineRunStarted>;
}
