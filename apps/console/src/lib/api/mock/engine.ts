import { ApiError } from '../contract';
import type { EngineApi } from '../engine-contract';

/** The workflow runner has no demo data: every call says so, and the pages show it as an error, not an empty list. */
export function createEngineMock(): EngineApi {
  const unavailable = async (): Promise<never> => {
    throw new ApiError('The workflow runner needs the agents service; the demo data has none.', 501);
  };
  return {
    nodeTypes: unavailable,
    definition: unavailable,
    validate: unavailable,
    publish: unavailable,
    deleteDefinition: unavailable,
    requestPublish: unavailable,
    setPaused: unavailable,
    options: unavailable,
    startRun: unavailable,
    startWorkflow: unavailable,
    runs: unavailable,
    run: unavailable,
    cancelRun: unavailable,
  };
}
