import type { PromptsApi } from '../../prompts-contract';
import { respond } from '../runtime';
import { VARIABLES } from './seed';

/** Prompt tooling in the mock: the variable list `{{` offers. A brief is drafted on the agent (agents.draftBrief). */
export function createPromptsMock() {
  const api: PromptsApi = {
    variables: () => respond(() => VARIABLES),
  };
  return { api };
}
