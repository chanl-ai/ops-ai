import type { BulkResult } from '@/lib/types/domain';
import type { EvalCase, EvalCaseFilters, EvalCaseInput, EvalCaseOptions, EvalRun, EvalRunFilters, EvalRunRow, EvalSuite, SaveTurnInput } from '@/lib/types/evals';
import type { ListParams, ListResult } from '@/lib/types/query';

/**
 * Agent evals. Every save of an agent starts a run on its own; `run` starts one on demand. A run tests the
 * agent's newest version and compares it with the version live workflows use.
 */
export interface EvalsApi {
  /** The agent's own test set and the platform sets attached to it, each with its latest pass rate. */
  suites(agentId: string): Promise<EvalSuite[]>;
  cases(agentId: string, params: ListParams<EvalCaseFilters>): Promise<ListResult<EvalCase>>;
  createCase(agentId: string, input: EvalCaseInput): Promise<EvalCase>;
  /** Rows that fail validation are skipped with the reason; ids are row indexes. */
  importCases(agentId: string, rows: EvalCaseInput[]): Promise<BulkResult>;
  /** Builds a case from one test-panel turn: its input, who it ran as, and what it called and cited. */
  caseFromTurn(agentId: string, input: SaveTurnInput): Promise<EvalCase>;
  /** 403 on a platform case. */
  removeCase(id: string): Promise<void>;
  bulkRemoveCases(ids: string[]): Promise<BulkResult>;
  run(agentId: string): Promise<EvalRun>;
  runs(agentId: string, params: ListParams<EvalRunFilters>): Promise<ListResult<EvalRunRow>>;
  getRun(runId: string): Promise<EvalRun>;
  /** The newest run, running or complete; null when none has run. */
  latest(agentId: string): Promise<EvalRun | null>;
  options(agentId: string): Promise<EvalCaseOptions>;
}
