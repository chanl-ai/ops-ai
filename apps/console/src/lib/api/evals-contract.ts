import type { EvalCase, EvalCaseInput, EvalRun } from '@/lib/types/evals';
import type { ListParams, ListResult } from '@/lib/types/query';

/**
 * Agent evals on agents-service: the agent's saved cases and its kept runs. Nothing starts a run on its own; one
 * happens when someone presses Run evals or runs `opsai agents eval`, and the call answers when it has finished.
 */
export interface EvalsApi {
  cases(agentId: string): Promise<EvalCase[]>;
  /** Adds these after the agent's last case and answers the whole saved set. An unknown check type or a judge without its rubric is 422. */
  addCases(agentId: string, cases: EvalCaseInput[]): Promise<EvalCase[]>;
  removeCase(id: string): Promise<void>;
  /** Runs the agent's saved cases and keeps the run; no saved cases is 422. */
  run(agentId: string): Promise<EvalRun>;
  /** Kept runs, newest first; the newest is page 1 with a page size of 1. */
  runs(agentId: string, params: ListParams): Promise<ListResult<EvalRun>>;
  getRun(runId: string): Promise<EvalRun>;
}
