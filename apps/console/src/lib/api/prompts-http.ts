import type { PromptsApi } from './prompts-contract';

type Get = <T>(path: string) => Promise<T>;

/** REST routes for prompt tooling. */
export function createPromptsHttp(get: Get): PromptsApi {
  return { variables: () => get('/prompts/variables') };
}
